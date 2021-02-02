from fesl_integration import check_analytical_integration, qe_dens_to_nr_of_electrons, qe_ldos_to_density, qe_ldos_to_dos
from tensor_memory import test_tensor_memory


''''
fesl_tests: Central hub for all subroutine tests for fesl.
'''
standard_accuracy = 10**-10

######################
# Memory tests (obsolete).
######################

if test_tensor_memory("../examples/data/Al_debug_2k_nr0.in.npy", standard_accuracy):
    print("test_tensor_memory suceeded.")
else:
    raise Exception("test_tensor_memory failed.")

######################
# Integration tests.
######################

if check_analytical_integration(standard_accuracy):
    print("check_analytical_integration suceeded.")
else:
    raise Exception("check_analytical_integration failed.")

# Find a way to provide these tests with data....

# if qe_dens_to_nr_of_electrons(standard_accuracy):
#     print("qe_dens_to_nr_of_electrons suceeded.")
# else:
#     raise Exception("qe_dens_to_nr_of_electrons failed.")
# if qe_ldos_to_density(standard_accuracy):
#     print("qe_ldos_to_density suceeded.")
# else:
#     raise Exception("qe_ldos_to_density failed.")
# if qe_ldos_to_dos(standard_accuracy):
#     print("qe_ldos_to_dos suceeded.")
# else:
#     raise Exception("qe_ldos_to_dos failed.")

######################
# Total energy test.
######################

# Find a way to access the total energy module form a runner.
# from total_energy_tester import test_total_energy
# if test_total_energy():
#     print("test_total_energy suceeded.")
# else:
#     raise Exception("test_total_energy failed.")
