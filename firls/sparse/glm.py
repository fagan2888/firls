from sklearn.utils.extmath import safe_sparse_dot
import numpy as np
from numba import vectorize, float64, njit


@vectorize([float64(float64)])
def log_inverse_logit(x):
    """Log of the logistic function log(e^x / (1 + e^x))"""
    if x > 0:
        return -np.log(1. + np.exp(-x))
    else:
        return x - np.log(1. + np.exp(x))


@vectorize([float64(float64)])
def inverse_logit(x):
    """The logistic function e^x / (1 + e^x) or e^x / (1 + e^x)"""
    if x > 0:
        return 1 / (1 + np.exp(-x))
    else:
        return +np.exp(x) / (1 + np.exp(x))


def _intercept_dot(w, X):
    """inspired by sklearn implentation."""
    c = 0.
    if w.size == X.shape[1] + 1:
        c = w[-1]
    w = w[:-1]
    z = safe_sparse_dot(X, w) + c
    return w, c, z


def _glm_loss_and_grad(w, X, y, alpha=0, familly="binomial", r=1,  sample_weight=None, ):
    """Computes the logistic loss and gradient.
    """
    n_samples, n_features = X.shape
    grad = np.empty_like(w)

    w, c, Xw_c = _intercept_dot(w, X, y)

    if sample_weight is None:
        sample_weight = np.ones(n_samples)

    if familly == "gaussian":
        mu = Xw_c
        out = np.sum(sample_weight * (y - mu) ** 2) + .5 * alpha * np.dot(w, w)
        z0 = -sample_weight * (y - mu)
    elif familly == "binomial":
        p = inverse_logit(Xw_c)
        out = -np.sum(sample_weight * (y * np.log(p) + (1 - y) * np.log(1 - p))) + .5 * alpha * np.dot(w, w)
        z0 = -sample_weight * (y - p)
    elif familly == "poisson":
        mu = np.exp(Xw_c)
        out = np.sum(sample_weight * (mu - y * Xw_c)) + .5 * alpha * np.dot(w, w)
        z0 = sample_weight * (mu - y)
    elif familly == "negativebinomial":
        mu = np.exp(Xw_c)
        p = mu / (mu + r)
        p_tilde = (y + r) * p
        out = -np.sum(sample_weight * (y * Xw_c - (y + r) * np.log(r + mu))) + .5 * alpha * np.dot(w, w)
        z0 = sample_weight * (p_tilde - y)

    grad[:n_features] = safe_sparse_dot(X.T, z0) + alpha * w

    if grad.shape[0] > n_features:
        grad[-1] = z0.sum()
    return out, grad
