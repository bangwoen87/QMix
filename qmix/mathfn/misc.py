"""Various math functions that do various things, variously.

"""

import numpy as np


# Simple derivatives ---------------------------------------------------------

def slope(x, y):
    """Simple derivative dy/dx.

    The derivative is centered and it is the same number of points as x/y.

    Args:
        x (ndarray): x data
        y (ndarray): y data

    Returns:
        ndarray: derivative

    """

    der = np.zeros(np.alen(x), dtype=float)

    rise = y[2:] - y[:-2]
    run = x[2:] - x[:-2]

    with np.errstate(divide='ignore'):
        der[1:-1] = rise / run
        der[0] = (y[1] - y[0]) / (x[1] - x[0])
        der[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])

    return der


def slope_span_n(x, y, n=11, nozeros=True):
    """Simple derivative, except the derivative is over a -N/2 to N/2 span.

    Helps with noisy data. Also deletes zero values since the results of this
    function are usually used to divide other values.

    Args:
        x (ndarray): x data
        y (ndarray): y data
        n (int): span, must be odd
        nozeros (bool): don't allow der=0 results

    Returns:
        ndarray: derivative

    """

    assert n % 2 == 1, "N must be odd."
    n = (n - 1) // 2

    der = np.zeros(np.alen(x), dtype=float)

    rise = y[2 * n + 1:] - y[:-2 * n - 1]
    run  = x[2 * n + 1:] - x[:-2 * n - 1]

    with np.errstate(divide='ignore'):
        der[n + 1:-n] = rise / run
        for n in range(1, n + 1):
            rise = y[2 * n + 1:] - y[:-2 * n - 1]
            run  = x[2 * n + 1:] - x[:-2 * n - 1]
            der[n]  = rise[n]  / run[n]
            der[-n] = rise[-n] / run[-n]

    der[0] = der[1]
    der[-1] = der[-2]

    if nozeros:
        der[der == 0] = 1e-10

    return der