import numpy as np
from scipy import optimize
from sklearn.linear_model.base import LinearClassifierMixin, BaseEstimator
from sklearn.utils.validation import check_X_y, check_array

from firls.irls import fit_irls
from firls.loss_and_grad import _glm_loss_and_grad
from firls.loss_and_grad import inverse_logit

VALID_FAMILLY = ["gaussian", "binomial", "bernouilli", "poisson", "negativebinomial"]
VALID_SOLVER = ["ccd", "inv"]


def _check_solver(solver, bounds, lambda_l1):
    """Helper function for selecting the solver.
    """
    if solver is not None:
        if solver not in VALID_SOLVER:
            raise ValueError("'solver' must be in " + repr(VALID_SOLVER))
        if lambda_l1 is not None and solver != "ccd":
            raise ValueError("Only ccd solver is allowed with 'lambda_l1'")

        return solver
    elif bounds is not None:
        return "ccd"
    elif lambda_l1 is not None:
        return "ccd"
    else:
        return "inv"


def _predict_glm(X, coef, family, intercept):
    if family == "gaussian":
        return X @ coef + intercept
    else:
        return np.exp(X @ coef + intercept)


class FastGlm(BaseEstimator, LinearClassifierMixin):
    """
    Base class for sharing methods. Defined properties respect sklearn
    naming convention of other linear models.
    """

    @property
    def coef_(self):
        return self._coef

    @property
    def intercept_(self):
        return self._intercept

    @property
    def family(self):
        return self._family

    def predict(self, X):
        """
        Predict using the glm family. For family="gaussian" the identity link is used
        otherwise the log link is used.

        Parameters
        ----------
        X : array
            data

        Returns
        -------
        Returns the predicted values.

        """
        if self.family == "binomial":
            return self.predict_proba(X)
        return _predict_glm(X, self.coef_, self.family, self.intercept_)

    def predict_proba(self, X):
        """
        Predict the class probability.

        Parameters
        ----------
        X : array
            data

        Returns
        -------
        Returns the class probability.

        """
        if self.family == "gaussian":
            raise NotImplemented()
        elif self.family == "binomial":
            return inverse_logit((X @ self.coef_) + self.intercept_)
        elif self.family == "poisson":
            return self
        return self


class GLM(FastGlm):
    """Generalized linear model with L1 and L2 penalties. Support box constraints.

        Minimizes the objective function::

        ||y - Xw - c||^2_2
        + lambda_l1  ||w||_1
        + 0.5 * lambda_l2 ||w||^2_2

        u.c. l_i <= w_i <= u_i, i = 1:p

    where c is the intercept, l_i and u_i the lower and upper bound for weights i.
    The bounds have to be defined for each weight. For instance for positive solution
    bounds = np.array([0,1e10]*p).

    Parameters
    ----------
    lambda_l1 : float, optional
        The norm 1 penalty parameter "Lasso".

    lambda_l2 : float, optional
        The norm 2 penalty parameter "Ridge.

    r: float, optional
        Failure rate for the negative binomial family. It is a floating number to be abble to use it for the
        Poisson-gamma regression.

    fit_intercept : bool
        Whether the intercept should be estimated or not. Note that the intercept is not regularized.

    family : str
        The target family distribution.

    bounds : array, optional
        Array of bounds. The first column is the lower bound. The second column is the upper bound.

    solver : str
        Solver to be used in the iterative reweighed least squared procedure.
        - "inv" : use the matrix inverse. This only works with lambda_l1=0.
        - "ccd" : use the cyclical coordinate descent.
        When lambda_l1>0 "ccd" is automatically selected. For problem with low dimension (p<1000) the "inv"
        method should be faster.

    max_iters : int
        Number of maximum iteration for the iterative reweighed least squared procedure.

    tol : float
        Convergence tolerance for the ccd algorithm. the algorithm stops when ||w - w_old ||_2 < tol.

    p_shrinkage : float
        Shrink the probabilities for better stability.

    """

    def __init__(
        self,
        lambda_l1=None,
        lambda_l2=None,
        r=1,
        fit_intercept=True,
        family="binomial",
        bounds=None,
        solver=None,
        max_iters=10000,
        tol=1e-8,
        p_shrinkage=1e-25,
    ):

        self.solver = _check_solver(solver, bounds, lambda_l1)
        self.lambda_l1 = float(lambda_l1) if lambda_l1 is not None else 0.0
        self.lambda_l2 = float(lambda_l2) if lambda_l2 is not None else 0.0
        self.r = float(r)

        if family not in VALID_FAMILLY:
            raise ValueError("'family' must be in " + repr(VALID_FAMILLY))
        self._family = str(family)
        self.bounds = bounds if bounds is None else check_array(bounds)
        self.fit_intercept = fit_intercept
        self.tol = float(tol)
        self.max_iters = int(max_iters)
        self.p_shrinkage = float(p_shrinkage)

    def fit(self, X, y):
        X, y = check_X_y(X, y, ensure_2d=True, accept_sparse=False)
        X = np.ascontiguousarray(X)
        y = np.ascontiguousarray(y)

        if y.ndim != 2:
            y = y.reshape((len(y), 1))

        coef_, irls_niter, ccd_niter = fit_irls(
            X,
            y,
            family=self._family,
            fit_intercept=self.fit_intercept,
            lambda_l1=float(self.lambda_l1) if self.lambda_l1 is not None else 0.0,
            lambda_l2=float(self.lambda_l2) if self.lambda_l2 is not None else 0.0,
            bounds=self.bounds,
            r=self.r,
            max_iters=self.max_iters,
            tol=self.tol,
            p_shrinkage=self.p_shrinkage,
            solver=self.solver,
        )
        self.irls_niter_ = irls_niter
        self.ccd_niter_ = ccd_niter
        coef = coef_.ravel()
        if self.fit_intercept:
            self._coef = coef[1:]
            self._intercept = coef[0]
        else:
            self._coef = coef
            self._intercept = 0
        return self


class SparseGLM(FastGlm):
    def __init__(
        self,
        family="binomial",
        lambda_l2=0,
        gamma=None,
        fit_intercept=False,
        bounds=None,
        solver="lbfgs",
        **solver_kwargs
    ):
        """Generalized linear model for sparse features with L2 penalties. Support box constraints.

            Minimizes the objective function::

            ||y - Xw - c||^2_2
            + 0.5 * lambda_l2 ||w||^2_2

            u.c. l_i <= w_i <= u_i, i = 1:p

        where c is the intercept, l_i and u_i the lower and upper bound for weights i.
        The bounds have to be defined for each weight. For instance for positive solution
        bounds = np.array([0,1e10]*p).

        Parameters
        ----------
        family : str
            The target family distribution.

        lambda_l2 : float, optional
            The norm 2 penalty parameter "Ridge".

        gamma : array, optional
            An positive definite matrix for the Tikhonov regularisation.


        fit_intercept : bool
            Whether the intercept should be estimated or not. Note that the intercept is not regularized.

        bounds : array, optional
            Array of bounds. The first column is the lower bound. The second column is the upper bound.

        solver : str
            Behind the scene optimize from Scipy module is called. Both "lbfgs" and "tcn" can be used. See
            the scipy doc for more information.
            - "lbfgs" : low memory bfgs (default).
            - "tcn" : truncated conjugate newton.

        solver_kwargs : dict
            parameters to be passed to the solver.

        """
        self._family = family
        self.solver = solver
        self.solver_kwargs = solver_kwargs
        self.fit_intercept = fit_intercept
        self.lambda_l2 = lambda_l2
        self.gamma = gamma

        self.bounds = bounds if bounds is None else check_array(bounds)

    def fit(self, X, y, sample_weight=None):

        X, y = check_X_y(X, y, ensure_2d=True, accept_sparse="csr", order="C")

        if self.fit_intercept:
            w0 = np.zeros(X.shape[1] + 1)
        else:
            w0 = np.zeros(X.shape[1])

        if self.solver == "lbfgs":
            coef, loss, info = optimize.fmin_l_bfgs_b(
                _glm_loss_and_grad,
                w0,
                fprime=None,
                bounds=self.bounds,
                args=(X, y, self.family, self.lambda_l2, self.gamma, 1, sample_weight),
                **self.solver_kwargs
            )
            self.info_ = info

        elif self.solver == "tcn":
            coef, nfeval, rc = optimize.fmin_tnc(
                _glm_loss_and_grad,
                w0,
                bounds=self.bounds,
                fprime=None,
                args=(X, y, self.family, self.lambda_l2, self.gamma, 1, sample_weight),
                **self.solver_kwargs
            )

        self.loss_value_, self.grad_value_ = _glm_loss_and_grad(
            coef, X, y, self.family, self.lambda_l2
        )
        self.loss_value_, self.grad_value_ = _glm_loss_and_grad(
            coef, X, y, self.family, self.lambda_l2
        )
        if self.fit_intercept:
            self._coef = coef[:-1]
            self._intercept = coef[-1]
        else:
            self._coef = coef
            self._intercept = 0
        return self
