""" This module contains functions to calculate the quasiparticle tunneling 
currents passing through an SIS junction. 

Description:

    Given the voltages applied across an SIS junction, the quasiparticle 
    tunneling currents can be calculated using multi-tone spectral domain 
    analysis (MTSDA; see references in online docs). 

Note: 

    This code is largely based on P. Kittara's 2002 DPhil thesis (see 
    references in online docs). I include some inline comments to refer to
    specific equations.

    Also, all of the values in this module are normalized, i.e., voltages are
    normalized to the gap voltage, frequencies are normalized to the gap 
    frequency, etc.

"""

from timeit import default_timer as timer

import math
import numba as nb
import numpy as np
from scipy.special import jv as bessel


# round vph values to this number of decimal places
# required when comparing vph to vph_list
ROUND_VPH = 4  


# Determine the dc/ac tunneling currents -------------------------------------

def qtcurrent(vj, cct, resp, vph_list, num_b=15, verbose=True, resp_matrix=None):
    """Calculate the quasiparticle tunneling current.

    This function uses multi-tone spectral domain analysis (MTSDA; see 
    references in online docs). The current is calculated based on the
    voltage applied across the junction.

    Note:

        This function will return the tunneling current for all of the 
        normalized photon voltages listed in vph_list. E.g., to solve for the 
        dc tunneling current and the ac tunneling current at 230 GHz, the 
        ``vph_list`` would  be ``[0, 230e9 / fgap]`` where ``fgap`` is the gap
        frequency.

        Maximum of 4 non-harmonic tones.

    Args:
        vj (ndarray): Voltage across the SIS junction
        cct (qmix.circuit.EmbeddingCircuit): Embedding circuit
        resp (qmix.respfn.RespFn): Response function
        vph_list: Calculate the tunneling currents for these photon voltages 
            (i.e., frequencies)

    Keyword arguments:
        num_b (float_or_tuple): Number of Bessel functions to include
        verbose (bool): Print to the terminal if true
        resp_matrix (ndarray): The interpolated response function matrix

    Returns:
        ndarray: Tunneling current

    """

    # Load, prepare and check input data -------------------------------------

    num_f = cct.num_f   # number of frequencies
    num_p = cct.num_p   # number of harmonics
    npts = cct.vb_npts  # number of bias voltages

    assert cct.vph[1:].min() > 0., "All vph must be > 0!"

    try:
        vph_list = list(vph_list)
        vph_is_list = True
    except TypeError:
        vph_list = [float(vph_list)]
        vph_is_list = False

    # TODO: there must be a better way...
    for i, vph_val in enumerate(vph_list):
        vph_list[i] = round(vph_list[i], ROUND_VPH)
    nvph = len(vph_list)

    vph = cct.vph

    nb_list = _unpack_num_b(num_b, num_f)

    if verbose:
        print("Calculating tunneling current...")
        print(" - {0} tone(s)".format(cct.num_f))
        print(" - {0} harmonic(s)".format(cct.num_p))
        start_time = timer()

    # Convolution coefficients ------------------------------------------------

    ccc = _convolution_coefficient(vj, vph, num_f, num_p, num_b)

    # Interpolate response function ------------------------------------------

    if resp_matrix is None:
        resp_matrix = interpolate_respfn(cct, resp, num_b)
    else:
        assert resp_matrix.ndim == num_f + 1
        assert resp_matrix.shape[-1] == npts

    # Call the correct function depending on the number of tones---------------

    current_out = np.zeros((nvph, cct.vb_npts), dtype=complex)

    if num_f == 1:
        for i in range(nvph):
            current_out[i] = _current_1_tone(vph_list[i], ccc, vph, resp_matrix, num_p, npts, *nb_list)
    elif num_f == 2:
        for i in range(nvph):
            current_out[i] = _current_2_tones(vph_list[i], ccc, vph, resp_matrix, num_p, npts, *nb_list)
    elif num_f == 3:
        for i in range(nvph):
            current_out[i] = _current_3_tones(vph_list[i], ccc, vph, resp_matrix, num_p, npts, *nb_list)
    elif num_f == 4:
        for i in range(nvph):
            current_out[i] = _current_4_tones(vph_list[i], ccc, vph, resp_matrix, num_p, npts, *nb_list)

    # Done --------------------------------------------------------------------

    if verbose:
        print("Done.")
        print("Time: {0:.4f} s\n".format(timer() - start_time))

    if vph_is_list:
        return current_out
    else:
        if vph_list[0] == 0.:
            return current_out[0].real
        else:
            return current_out[0]


# Other tunneling current functions ------------------------------------------
# All of the functions below use tunneling_current, but they return the
# tunneling current for different frequencies or in different formats (based
# on the needs of other functions/modules).

def qtcurrent_all_freq(vj, cct, resp, num_b=15):
    """Calculate the AC tunneling current for all tones and all harmonics.

    This function will return the tunneling current in a 3-D array: 
    (num_f+1) x (num_p+1) x (npts).

    Args:
        vj (ndarray): Voltage across the junction
        cct (qmix.circuit.EmbeddingCircuit): Embedding circuit class
        resp (qmix.respfn.RespFn): Response function

    Keyword arguments:
        num_b (int_or_tuple): Number of Bessel functions to include

    Returns:
        ndarray: Tunneling current

    """

    num_f = cct.num_f
    num_p = cct.num_p
    npts = cct.vb_npts

    # Get vph list with all tones/harmonics represented
    vph_list = (cct.vph[1:, None] * np.arange(1, num_p+1)).flatten()

    current = qtcurrent(vj, cct, resp, vph_list, num_b, verbose=False)

    # Arrange back into a 3D matrix (f x p x vb)
    current_out = np.zeros((num_f + 1, num_p + 1, npts), dtype=complex)
    current_out[1:, 1:] = current.reshape((num_f, num_p, npts))

    return current_out


def qtcurrent_std(vj, cct, resp, num_b=15):
    """Calculate the 'standard' tunneling currents: DC, LO and IF.

    Assumes that ``cct.vph[1]`` is the LO signal, 
    ``cct.vph[2]`` is the RF signal, and that
    ``cct.vph[2] - cct.vph[1]`` is the frequency of the IF signal.

    The simulation can have 2, 3, or 4 tones.

    Args:
        vj (ndarray): Voltage across the junction
        cct (qmix.circuit.EmbeddingCircuit): Embedding circuit
        resp (qmix.respfn.RespFn): Response function

    Keyword arguments:
        num_b (int_or_tuple): Number of Bessel functions to include

    Returns:
        ndarray: DC tunneling current
        ndarray: AC tunneling current at f = LO
        ndarray: AC tunneling current at f = IF

    """

    vph_lo = cct.vph[1]
    vph_rf = cct.vph[2]
    vph_if = abs(vph_lo - vph_rf)

    vph_list = [0, vph_lo, vph_if]
    results = qtcurrent(vj, cct, resp, vph_list, num_b, verbose=False)

    current_dc = results[0, :].real
    current_lo = results[1, :]
    current_if = results[2, :]

    return current_dc, current_lo, current_if


# Response function matrices --------------------------------------------------
# The response function (the dc I-V curve and it's KK transform) need to be
# repeatedly interpolated in this module. The functions below do all of the
# necessary interpolations all at once to save time.
#
# Interpolating the response function is one of the most time consuming 
# operations within this module.
#
# Two different methods are used below to generate the interpolation voltages:
#    - one using loops
#    - one without
# I've spent some time optimizing each and using the correct method for each
# number of tones.
#
# Runs once per qtcurrent function call

def interpolate_respfn(cct, resp, num_b):
    """Interpolate the response function at all necessary voltages.

    I have included this as a stand-alone function because if you are going
    to be running ``qtcurrent`` over and over again with the same input 
    signal frequencies, it can save time by pre-interpolating the response 
    function.

    Args:
        cct (qmix.circuit.EmbeddingCircuit): Embedding circuit
        resp (qmix.respfn.RespFn): Response function
        num_b (int/tuple): Number of Bessel functions to include.

    Returns:
        ndarray: The interpolated response function as a matrix.

    """

    nb_list = _unpack_num_b(num_b, cct.num_f)

    if cct.num_f == 1:
        resp_matrix = _find_resp_current_1_tone(resp, cct.vb, cct.vph, *nb_list)
    elif cct.num_f == 2:
        resp_matrix = _find_resp_current_2_tones(resp, cct.vb, cct.vph, *nb_list)
    elif cct.num_f == 3:
        resp_matrix = _find_resp_current_3_tones(resp, cct.vb, cct.vph, *nb_list)
    elif cct.num_f == 4:
        resp_matrix = _find_resp_current_4_tones(resp, cct.vb, cct.vph, *nb_list)
    else:
        print("num_f must be 1, 2, 3 or 4!")
        raise ValueError

    return resp_matrix


def _find_resp_current_1_tone(resp, vb, vph, num_b1):

    npts = len(vb)
    k_npts = num_b1 * 2 + 1
    vb_tmp = vb[None, :] * np.ones(k_npts)[:, None]
    ind = np.r_[np.arange(0, num_b1+1), np.arange(-num_b1, 0)]
    k_array = ind[:, None] * np.ones(npts, dtype=int)[None, :]
    resp_current_out = resp(vb_tmp + k_array * vph[1])

    # # DEBUG
    # print k_array[:,0]
    # print len(k_array[0,:])
    # print " {} -> {}".format(-num_b1, k_array[-num_b1][0])
    # print " 0 -> {}".format(k_array[0][0])
    # print " {} -> {}".format(num_b1, k_array[num_b1][0])

    return resp_current_out


def _find_resp_current_2_tones(resp, vb, vph, num_b1, num_b2):

    npts = len(vb)
    k_npts = num_b1 * 2 + 1
    l_npts = num_b2 * 2 + 1

    ind = np.r_[np.arange(0, num_b1 + 1), np.arange(-num_b1, 0)]
    k_array = ind[:, None, None] * np.ones((l_npts, npts), dtype=int)[None, :, :] 

    ind = np.r_[np.arange(0, num_b2 + 1), np.arange(-num_b2, 0)]
    l_array = ind[None, :, None] * np.ones((k_npts, npts), dtype=int)[:, None, :] 

    vb_tmp = vb[None, None, :] * np.ones((k_npts, l_npts))[:, :, None]
    resp_current_out = resp(vb_tmp + k_array * vph[1] + l_array * vph[2])

    # # DEBUG
    # print k_array[:,0,0]
    # print " {} -> {}".format(-num_b1, k_array[-num_b1][0,0])
    # print " {} -> {}".format(0, k_array[0][0,0])
    # print " {} -> {}".format(num_b1, k_array[num_b1][0,0])
    # print l_array[0,:,0]
    # print " {} -> {}".format(-num_b2, l_array[:,-num_b2][0,0])
    # print " {} -> {}".format(0, l_array[:,0][0,0])
    # print " {} -> {}".format(num_b2, l_array[:,num_b2][0,0])

    return resp_current_out


def _find_resp_current_3_tones(resp, vb, vph, num_b1, num_b2, num_b3):

    npts = len(vb)
    voltage = np.zeros((num_b1 * 2 + 1, num_b2 * 2 + 1, num_b3 * 2 + 1, npts))
    for k in range(-num_b1, num_b1 + 1):
        for l in range(-num_b2, num_b2 + 1):
            for m in range(-num_b3, num_b3 + 1):
                voltage[k, l, m] = vb + k * vph[1] + l * vph[2] + m * vph[3]
    resp_current_out = resp(voltage)

    return resp_current_out


def _find_resp_current_4_tones(resp, vb, vph, num_b1, num_b2, num_b3, num_b4):

    npts = len(vb)
    voltage = np.zeros((num_b1 * 2 + 1, num_b2 * 2 + 1, num_b3 * 2 + 1, num_b4 * 2 + 1, npts))
    for k in range(-num_b1, num_b1 + 1):
        for l in range(-num_b2, num_b2 + 1):
            for m in range(-num_b3, num_b3 + 1):
                for n in range(-num_b4, num_b4 + 1):
                    voltage[k, l, m, n, :] = vb + k * vph[1] + l * vph[2] + m * vph[3] + n * vph[4]
    resp_current_out = resp(voltage)

    return resp_current_out


# Calculate the convolution coefficients -------------------------------------

def _convolution_coefficient(vj, vph, num_f, num_p, num_b):
    """Calculate the convolution coefficients for each tone.

    The convolution coefficients contains all of the spectral data (amplitudes
    and phases). They are found through an iterative technique. 
    
    Runs once per qtcurrent function call

    Note: 

        I originally wrote these functions using linear algebra/recursion/
        broadcasting, but I found the method used below to be faster.

    Args:
        vj (ndarray): Voltage across the SIS junction
        vph (ndarray): Photon voltages
        num_f (int): Number of non-harmonically related frequencies
        num_p (int): Number of harmonics
        num_b (int): Number of Bessel functions

    Returns:
        ndarray: Coefficients

    """

    npts = len(vj[0, 0, :])
    if isinstance(num_b, tuple):
        num_b = max(num_b)

    # Junction drive level:  alpha[f, p, i] in R^(num_f+1)(num_p+1)(npts)
    alpha = np.zeros_like(vj, dtype=float)
    for f in range(1, num_f + 1):
        for p in range(1, num_p + 1):
            alpha[f, p, :] = np.abs(vj[f, p, :]) / (p * vph[f])

    # Junction voltage phase:  phi[f, p, i] in R^(num_f+1)(num_p+1)(npts)
    phi = np.angle(vj)  # in radians

    # Jacobi-Angers coefficients: jac[f, p, n, i] in C^(num_f+1)(num_p+1)(num_b*2+1)(npts)
    # Equation 5.7 in Kittara's thesis
    # Note: This chunk of code dominates the computation time of this function
    # Note: I tried using the recurrence relation, but ran into numerical errors
    jac = np.zeros((num_f + 1, num_p + 1, num_b * 2 + 1, npts), dtype=complex)
    for f in range(1, num_f + 1):
        for p in range(1, num_p + 1):
            jac[f, p,  0] =  bessel(0, alpha[f, p])
            for n in range(1, num_b + 1):
                jn = bessel(n, alpha[f, p])
                jac[f, p,  n] =           jn * np.exp(-1j * n * phi[f, p])
                jac[f, p, -n] = (-1)**n * jn * np.exp( 1j * n * phi[f, p])

    # Convolution coefficients: cc[f, k, i] in C^(num_f+1)(num_b*2+1)(npts)
    cc_out = _calculate_coeff(jac)

    # # DEBUG
    # import matplotlib.pyplot as plt 
    # plt.figure()
    # for f in range(1, num_f+1):
    #     # plt.stem(vph[f]*np.arange(-num_b, num_b+1), np.abs(cc_out[f, :, 70]))
    #     plt.stem(np.abs(cc_out[f, :, 70]))
    # plt.show()

    return cc_out


@nb.njit("c16[:,:,:](c16[:,:,:,:])")
def _calculate_coeff(jac):  # pragma: no cover
    """Calculate convolution coefficients (recursively).

    This function is only used if num_p > 1 !!!

    Calculation time is proportional to num_p.

    Args:
        jac (ndarray): Jacobi-Angers coefficients (from Eqn. 5.7)

    Returns:
        ndarray: Convolution coefficients

    """

    _, num_p, num_b, _ = jac.shape
    num_p -= 1                # number of harmonics
    num_b = (num_b - 1) // 2  # number of bessel functions

    ccc_last = jac[:, 1, :, :]
    if num_p == 1:
        return ccc_last

    for p in range(2, num_p + 1):
        ccc_next = np.zeros_like(ccc_last)
        for k in range(-num_b, num_b + 1):
            for l in range(-num_b, num_b + 1):
                idx = k - p * l
                if -num_b <= idx <= num_b:
                    ccc_next[1:, k] += ccc_last[1:, idx] * jac[1:, p, l]
        ccc_last = ccc_next

    return ccc_last


# Tunneling current functions ------------------------------------------------
# These are the functions that actually calculate the tunneling currents.
# Different functions are provided for different numbers of tones. They are
# all built the same way except that every additional tone will add another
# layer of coefficients and for-loops.

### One tone ###

def _current_1_tone(vph_out, ccc, vph, resp_matrix, num_p, npts, num_b1):
    """Calculate the tunneling current at a specific frequency.

    One tone.

    """

    vph_out = round(vph_out, ROUND_VPH)
    current_out = np.zeros(npts, dtype=complex)
    
    for a in range(num_p, -(num_p + 1), -1):

        vph_a = round(a * vph[1], ROUND_VPH)

        if vph_a == vph_out:

            current_out += _current_coeff_1_tone(a, ccc, resp_matrix, num_b1, npts)

    return current_out


@nb.njit("c16[:](i4, c16[:,:,:], c16[:,:], i4, i4)")
def _current_coeff_1_tone(a, ccc, resp_matrix, num_b1, npts):  # pragma: no cover
    """This function will calculate the tunneling current coefficient
        (I(a)) for a one tone system. Equations 5.17 and 5.18 in Kittara's
        thesis.
    """

    # Equation 5.17
    rs_p = np.zeros(npts, dtype=np.complex128)  # positive coefficients
    rs_m = np.zeros(npts, dtype=np.complex128)  # negative coefficients
    ccc_conj = np.conj(ccc[1])
    for k in range(-num_b1, num_b1 + 1):

        if -num_b1 <= k + a <= num_b1:
            rs_p += ccc[1, k, :] * ccc_conj[k + a, :] * resp_matrix[k]

        if -num_b1 <= k - a <= num_b1:
            rs_m += ccc[1, k, :] * ccc_conj[k - a, :] * resp_matrix[k]

    # Calculate current coefficient: equation 5.26
    if a == 0:
        return rs_p.imag + 1j * 0
    else:
        return (rs_p.imag + rs_m.imag) - 1j * (rs_p.real - rs_m.real)


### Two tones ###

def _current_2_tones(vph_out, ccc, vph, resp_matrix, num_p, npts, num_b1, num_b2):
    """Calculate the tunneling current at a specific frequency.

    Two tones.
    
    """

    vph_out = round(vph_out, ROUND_VPH)
    current_out = np.zeros(npts, dtype=complex)
    
    for a in range(num_p, -(num_p + 1), -1):
        for b in range(num_p, -(num_p + 1), -1):

            vph_ab = round(a * vph[1] + b * vph[2], ROUND_VPH)

            if vph_ab == vph_out:

                current_out += _current_coeff_2_tones(a, b, ccc, resp_matrix, num_b1, num_b2, npts)

    return current_out


@nb.njit("c16[:](i4, i4, c16[:,:,:], c16[:,:,:], i4, i4, i4)")
def _current_coeff_2_tones(a, b, ccc, resp_matrix, num_b1, num_b2, npts):  # pragma: no cover
    """This function will calculate the tunneling current coefficient
        (I(a,b)) for a two tone system (i.e., for a (a,b) pair versus
        calculating the entire matrix for every (a,b) pair). Equations 5.25
        and 5.26 in Kittara's thesis.
    """

    # Equation 5.25
    rs_p = np.zeros(npts, dtype=np.complex128)
    rs_m = np.zeros(npts, dtype=np.complex128)
    ccc_conj = np.conj(ccc)
    for k in range(-num_b1, num_b1 + 1):
        for l in range(-num_b2, num_b2 + 1):

            if -num_b1 <= k + a <= num_b1 and \
               -num_b2 <= l + b <= num_b2:
                rs_p += ccc[1, k, :] * ccc_conj[1, k + a, :] * \
                        ccc[2, l, :] * ccc_conj[2, l + b, :] * \
                        resp_matrix[k, l]

            if -num_b1 <= k - a <= num_b1 and \
               -num_b2 <= l - b <= num_b2:
                rs_m += ccc[1, k, :] * ccc_conj[1, k - a, :] * \
                        ccc[2, l, :] * ccc_conj[2, l - b, :] * \
                        resp_matrix[k, l]

    # Calculate current coefficient: equation 5.26
    if a == 0 and b == 0:
        return rs_p.imag + 1j * 0.
    else:
        return (rs_p.imag + rs_m.imag) - 1j * (rs_p.real - rs_m.real)


### Three tones ###

def _current_3_tones(vph_out, ccc, vph, resp_matrix, num_p, npts, num_b1, num_b2, num_b3):
    """Calculate the tunneling current at a specific frequency.

    Three tones.
    
    """

    # # Debug
    # print "\nVph: ", vph_out

    vph_out = round(vph_out, ROUND_VPH)
    current_out = np.zeros(npts, dtype=complex)

    for a in range(num_p, -(num_p + 1), -1):
        for b in range(num_p, -(num_p + 1), -1):
            for c in range(num_p, -(num_p + 1), -1):

                vph_abc = round(a * vph[1] + b * vph[2] + c * vph[3], ROUND_VPH)

                # # Debug
                # match = vph_abc == vph_out
                # if not match:
                #     match = ''
                # else:
                #     match = 'match!'
                # print "{:+d} {:+d} {:+d} {:+7.4f} {}".format(a, b, c, vph_abc, match)

                if vph_abc == vph_out:

                    # # Debug
                    # msg = "\t -> {:+d}*{:.4f} {:+d}*{:.4f} {:+d}*{:10.4f} = {:.4f}"
                    # print msg.format(a, vph[1], 
                    #                  b, vph[2],
                    #                  c, vph[3], vph_out)

                    current_out += _current_coeff_3_tones(a, b, c, ccc, resp_matrix,
                                                          num_b1, num_b2, num_b3)

    return current_out


@nb.njit("c16[:](i4, i4, i4, c16[:,:,:], c16[:,:,:,:], i4, i4, i4)")
def _current_coeff_3_tones(a, b, c, ccc, resp_matrix, num_b1, num_b2, num_b3):  # pragma: no cover
    """This function will calculate the tunneling current coefficient
        (I(a,b,c)) for a three tone system (i.e., for an (a,b,c) pair versus
        calculating the entire matrix for every (a,b,c) pair). Equations 5.25
        and 5.26 in Kittara's thesis.
    """

    # Recast cofficients
    ccc1 = ccc[1]
    ccc2 = ccc[2]
    ccc3 = ccc[3]

    # Equation 5.25
    rs_p = np.zeros_like(ccc1[0,:], dtype=np.complex128)
    rs_m = np.zeros_like(ccc1[0,:], dtype=np.complex128)
    for k in range(-num_b1, num_b1 + 1):
        for l in range(-num_b2, num_b2 + 1):
            for m in range(-num_b3, num_b3 + 1):

                c0 = ccc1[k] * ccc2[l] * ccc3[m]
                resp_current = resp_matrix[k, l, m]

                if -num_b1 <= k + a <= num_b1 and \
                   -num_b2 <= l + b <= num_b2 and \
                   -num_b3 <= m + c <= num_b3:

                    cp = np.conj(ccc1[k + a, :] *
                                 ccc2[l + b, :] *
                                 ccc3[m + c, :]) * c0

                    rs_p += cp * resp_current

                if -num_b1 <= k - a <= num_b1 and \
                   -num_b2 <= l - b <= num_b2 and \
                   -num_b3 <= m - c <= num_b3:

                    cm = np.conj(ccc1[k - a, :] *
                                 ccc2[l - b, :] *
                                 ccc3[m - c, :]) * c0

                    rs_m += cm * resp_current

    # Calculate current coefficient: equation 5.26
    if a == 0 and b == 0 and c == 0:
        return rs_p.imag + 1j * 0.
    else:
        return (rs_p.imag + rs_m.imag) - 1j * (rs_p.real - rs_m.real)


### Four tones ###

# @nb.njit("c16[:](f4, c16[:,:,:], f8[:], c16[:,:,:,:,:], i4, i4, i4, i4, i4, i4)")
def _current_4_tones(vph_out, ccc, vph, resp_matrix, num_p, npts, num_b1, num_b2, num_b3, num_b4):  # pragma: no cover
    """Calculate the tunneling current at a specific frequency (4 tones).

    Four tones.
    
    """

    vph_out = round(vph_out, ROUND_VPH)
    current_out = np.zeros(npts, dtype=np.complex128)

    for a in range(num_p, -(num_p + 1), -1):
        for b in range(num_p, -(num_p + 1), -1):
            for c in range(num_p, -(num_p + 1), -1):
                for d in range(num_p, -(num_p + 1), -1):

                    vph_abcd = round(a * vph[1] + b * vph[2] + c * vph[3] + d * vph[4], ROUND_VPH)

                    if vph_abcd == vph_out:

                        current_out += _current_coeff_4_tones(a, b, c, d, ccc, resp_matrix, 
                                                              num_b1, num_b2, num_b3, num_b4, npts)

    return current_out


@nb.njit("c16[:](i4, i4, i4, i4, c16[:,:,:], c16[:,:,:,:,:], i4, i4, i4, i4, i4)")
def _current_coeff_4_tones(a, b, c, d, ccc, resp_matrix, num_b1, num_b2, num_b3, num_b4, npts):  # pragma: no cover
    """This function will calculate the tunneling current coefficient
        (I(a,b,c,d)) for a four tone system (i.e., for an (a,b,c,d) pair
        versus calculating the entire matrix for every (a,b,c) pair).
        Equations 5.25 and 5.26 in Kittara's thesis.
    """

    # Recast coefficients (saves a bit of time)
    ccc1 = ccc[1]
    ccc2 = ccc[2]
    ccc3 = ccc[3]
    ccc4 = ccc[4]

    # Calculate Rabcd+j*Sabcd: quation 5.25
    rs_p = np.zeros(npts, dtype=np.complex128)  # positive abcd indices
    rs_m = np.zeros(npts, dtype=np.complex128)  # negative abcd indices
    for k in range(-num_b1, num_b1 + 1):
        for l in range(-num_b2, num_b2 + 1):
            for m in range(-num_b3, num_b3 + 1):
                for n in range(-num_b4, num_b4 + 1):

                    c0 = ccc1[k] * ccc2[l] * ccc3[m] * ccc4[n]

                    # Response function
                    resp_current = resp_matrix[k, l, m, n]

                    # Positive abcd indices
                    if -num_b1 <= k + a <= num_b1 and \
                       -num_b2 <= l + b <= num_b2 and \
                       -num_b3 <= m + c <= num_b3 and \
                       -num_b4 <= n + d <= num_b4:

                        cp = np.conj(ccc1[k + a] *
                                     ccc2[l + b] *
                                     ccc3[m + c] *
                                     ccc4[n + d]) * c0

                        rs_p += cp * resp_current

                    # Negative abcd indices
                    if -num_b1 <= k - a <= num_b1 and \
                       -num_b2 <= l - b <= num_b2 and \
                       -num_b3 <= m - c <= num_b3 and \
                       -num_b4 <= n - d <= num_b4:
                        
                        cm = np.conj(ccc1[k - a] *
                                     ccc2[l - b] *
                                     ccc3[m - c] *
                                     ccc4[n - d]) * c0
                        
                        rs_m += cm * resp_current

    # Calculate current coefficient: equation 5.26
    if a == 0 and b == 0 and c == 0 and d == 0:
        return rs_p.imag + 1j * 0.
    else:
        return (rs_p.imag + rs_m.imag) - 1j * (rs_p.real - rs_m.real)


# Helper functions -----------------------------------------------------------

def _unpack_num_b(num_b, num_f):
    """Unpack num_b (number of Bessel functions to include).

    Args:
        num_b: Number of Bessel functions to include
        num_f: Number of frequencies

    Returns:
        tuple: Number of Bessel functions in tuple form

    """

    # Note: num_b is 0-indexed if it is a tuple
    # I.e.: num_b[0] is for the fundamental frequency
    if isinstance(num_b, tuple):
        assert len(num_b) >= num_f, \
            "There must be one value of num_b for each fundamental frequency."
        num_b = tuple(num_b[:num_f])
        return num_b

    return tuple([num_b] * num_f)
