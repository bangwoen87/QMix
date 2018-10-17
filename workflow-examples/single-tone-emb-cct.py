""" single-tone-emb-cct.py

- This simulation is a bit more complex than `single-tone-simple.py`
    - The input still only consists of only one tone
    - The DC I-V curve is still generated by a polynomial model
    - The embedding circuit is now included

- This simulation calculates:
    - the pumped I-V curve
    - the AC tunnelling currents
    - the DC power delivered to the junction
    - the AC power delivered to the junction

- These are plotted and saved as `single-tone-emb-cct.py`

"""

import qmix
import numpy as np
import matplotlib.pyplot as plt
import scipy.constants as sc

# see: https://github.com/garrettj403/SciencePlots/
# plt.style.use('science')

qmix.print_intro()

# Define junction properties -------------------------------------------------

vgap = 2.7e-3              # gap voltage in [V]
rn = 13.5                  # normal resistance in [ohms]
igap = vgap / rn           # gap current in [A]
fgap = sc.e * vgap / sc.h  # gap frequency in [Hz]

# Define circuit parameters --------------------------------------------------

num_f = 1  # number of tones
num_p = 1  # number of harmonics

cct = qmix.circuit.EmbeddingCircuit(num_f, num_p)

# photon voltage:  vph[f] in R^(num_f+1)
cct.vph[1] = 230e9 / fgap

# embedding circuit for first tone/harmonic
cct.vt[1,1] = 0.5           # embedding voltage
cct.zt[1,1] = 0.3 - 1j*0.3  # embedding impedance

cct.print_info()

# Load desired response function ---------------------------------------------

# use polynomial model for DC I-V curve (order=40)
resp = qmix.respfn.RespFnPolynomial(40)

# Perform harmonic balance ---------------------------------------------------

# solve for voltage across junction
vj = qmix.harmonic_balance.harmonic_balance(cct, resp)

# Calculate desired tunnelling currents --------------------------------------

vph_output_list = [0, cct.vph[1]]
current = qmix.qtcurrent.qtcurrent(vj, cct, resp, vph_output_list)
idc = current[0].real
iac = current[1]

# Post-processing ------------------------------------------------------------

fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(8,7))
plt.subplots_adjust(wspace = 0.4)

vmv = vgap / sc.milli 
ima = igap / sc.milli 
iua = igap / sc.micro
iua = igap / sc.micro

voltage_label    = 'Bias Voltage (mV)'
current_label    = 'DC Tunnelling Current (uA)'
ac_current_label = 'AC Tunnelling Current (uA)'

# Plot DC tunnelling currents
ax1.plot(resp.voltage*vmv, resp.current*iua, label='Unpumped')
ax1.plot(cct.vb*vmv, idc*iua, 'r', label='Pumped')
ax1.set(xlabel=voltage_label, xlim=(0,5))
ax1.set(ylabel=current_label, ylim=(0,400))
ax1.legend(frameon=False,)

# Plot AC tunnelling currents
ax2.plot(cct.vb*vmv, np.abs(iac)*iua, 'k--', label=r'$\vert I_\omega\vert$')
ax2.plot(cct.vb*vmv, np.real(iac)*iua, label=r'Re$\{I_\omega\}$')
ax2.plot(cct.vb*vmv, np.imag(iac)*iua, 'r', label=r'Im$\{I_\omega\}$')
ax2.set(xlabel=voltage_label, xlim=(0,5))
ax2.set(ylabel=ac_current_label, ylim=(0,200))
ax2.legend(frameon=False,)

# Plot AC power delievered to junction
label_str = r'$P_\omega=\frac{1}{2}\mathrm{Re}\{V_\omega\,I_\omega^*\}$'
ac_power = 0.5 * np.real((vj[1,1]*vgap) * (np.conj(iac)*igap))
ax3.plot(cct.vb*vmv, ac_power/sc.nano, label=label_str)
ax3.set(xlabel=voltage_label, xlim=(0,5))
ax3.set(ylabel='AC Power (nW)', ylim=(0, 60))
ax3.legend(frameon=False,loc=0)

# Plot DC + AC power delievered to junction
dc_power = (idc*igap) * (cct.vb*vgap)
ax4.plot(cct.vb*vmv, ac_power/sc.micro, 'b:', label=r'$P_\omega$')
ax4.plot(cct.vb*vmv, (dc_power)/sc.micro, 'g--', label=r'$P_\mathrm{dc}$')
ax4.plot(cct.vb*vmv, (dc_power + ac_power)/sc.micro, 'r', label=r'$P_\omega+P_\mathrm{dc}$')
ax4.set(xlabel=voltage_label, xlim=(0,5))
ax4.set(ylabel='Power (uW)', ylim=(0,2))
ax4.legend(frameon=False,loc=2)

fig.suptitle(r'$\nu_\mathrm{{LO}}=230$~GHz, $V_\mathrm{{LO}}={:.1f}$ mV, $Z_\mathrm{{LO}}={:.1f} - j {:.1f}~\Omega$'.format(cct.vt[1,1].real*vgap*1e3, cct.zt[1,1].real*rn, -cct.zt[1,1].imag*rn))

fig.savefig('single-tone-emb-cct.png', dpi=500)
