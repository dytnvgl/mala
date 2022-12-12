"""Base class for all descriptor calculators."""
from abc import ABC, abstractmethod

import ase
import numpy as np

from mala.common.parameters import ParametersDescriptors, Parameters
from mala.common.parallelizer import get_comm, printout, get_rank, get_size, \
    barrier, parallel_warn


class Descriptor(ABC):
    """
    Base class for all descriptors available in MALA.

    Descriptors encode the atomic fingerprint of a DFT calculation.

    Parameters
    ----------
    parameters : mala.common.parameters.Parameters
        Parameters object used to create this object.

    """

    def __new__(cls, params: Parameters):
        """
        Create a Descriptor instance.

        The correct type of descriptor calculator will automatically be
        instantiated by this class if possible. You can also instantiate
        the desired descriptor directly by calling upon the subclass.

        Parameters
        ----------
        params : mala.common.parametes.Parameters
            Parameters used to create this descriptor calculator.
        """
        descriptors = None
        # Check if we're accessing through base class.
        # If not, we need to return the correct object directly.
        if cls == Descriptor:
            if params.descriptors.descriptor_type == 'SNAP':
                from mala.descriptors.bispectrum import Bispectrum
                parallel_warn(
                    "Using 'SNAP' as descriptors will be deprecated "
                    "starting in MALA v1.3.0. Please use 'Bispectrum' "
                    "instead.",  min_verbosity=0, category=FutureWarning)
                descriptors = super(Descriptor, Bispectrum).__new__(Bispectrum)

            if params.descriptors.descriptor_type == 'Bispectrum':
                from mala.descriptors.bispectrum import Bispectrum
                descriptors = super(Descriptor, Bispectrum).__new__(Bispectrum)

            if params.descriptors.descriptor_type == "AtomicDensity":
                from mala.descriptors.atomic_density import AtomicDensity
                descriptors = super(Descriptor, AtomicDensity).\
                    __new__(AtomicDensity)

            if descriptors is None:
                raise Exception("Unsupported descriptor calculator.")
        else:
            descriptors = super(Descriptor, cls).__new__(cls)

        return descriptors

    def __init__(self, parameters):
        self.parameters: ParametersDescriptors = parameters.descriptors
        self.fingerprint_length = -1  # so iterations will fail
        self.dbg_grid_dimensions = parameters.debug.grid_dimensions
        self.verbosity = parameters.verbosity
        self.in_format_ase = ""
        self.grid_dimensions = []

    @property
    def descriptors_contain_xyz(self):
        """Control whether descriptor vectors will contain xyz coordinates."""
        return self.parameters.descriptors_contain_xyz

    @descriptors_contain_xyz.setter
    def descriptors_contain_xyz(self, value):
        self.parameters.descriptors_contain_xyz = value

    @staticmethod
    def convert_units(array, in_units="1/eV"):
        """
        Convert descriptors from a specified unit into the ones used in MALA.

        Parameters
        ----------
        array : numpy.array
            Data for which the units should be converted.

        in_units : string
            Units of array.

        Returns
        -------
        converted_array : numpy.array
            Data in MALA units.

        """
        raise Exception("No unit conversion method implemented for this"
                        " descriptor type.")

    @staticmethod
    def backconvert_units(array, out_units):
        """
        Convert descriptors from MALA units into a specified unit.

        Parameters
        ----------
        array : numpy.array
            Data in MALA units.

        out_units : string
            Desired units of output array.

        Returns
        -------
        converted_array : numpy.array
            Data in out_units.

        """
        raise Exception("No unit back conversion method implemented for "
                        "this descriptor type.")

    @staticmethod
    def enforce_pbc(atoms):
        """
        Explictly enforces the PBC on an ASE atoms object.

        QE (and potentially other codes?) do that internally. Meaning that the
        raw positions of atoms (in Angstrom) can lie outside of the unit cell.
        When setting up the DFT calculation, these atoms get shifted into
        the unit cell. Since we directly use these raw positions for the
        descriptor calculation, we need to enforce that in the ASE atoms
        objects, the atoms are explicitly in the unit cell.

        Parameters
        ----------
        atoms : ase.atoms
            The ASE atoms object for which the PBC need to be enforced.

        Returns
        -------
        new_atoms : ase.Atoms
            The ASE atoms object for which the PBC have been enforced.
        """
        new_atoms = atoms.copy()
        new_atoms.set_scaled_positions(new_atoms.get_scaled_positions())

        # This might be unecessary, but I think it is nice to have some sort of
        # metric here.
        rescaled_atoms = 0
        for i in range(0, len(atoms)):
            if False in (np.isclose(new_atoms[i].position,
                          atoms[i].position, atol=0.001)):
                rescaled_atoms += 1
        printout("Descriptor calculation: had to enforce periodic boundary "
                 "conditions on", rescaled_atoms, "atoms before calculation.",
                 min_verbosity=2)
        return new_atoms

    def calculate_from_qe_out(self, qe_out_file, working_directory=".",
                              **kwargs):
        """
        Calculate the descriptors based on a Quantum Espresso outfile.

        Parameters
        ----------
        qe_out_file : string
            Name of Quantum Espresso output file for snapshot.

        working_directory : string
            A directory in which to write the output of the LAMMPS calculation.
            Usually the local directory should suffice, given that there
            are no multiple instances running in the same directory.

        Returns
        -------
        descriptors : numpy.array
            Numpy array containing the descriptors with the dimension
            (x,y,z,descriptor_dimension)

        """
        self.in_format_ase = "espresso-out"
        printout("Calculating descriptors from", qe_out_file,
                 min_verbosity=0)
        # We get the atomic information by using ASE.
        atoms = ase.io.read(qe_out_file, format=self.in_format_ase)

        # Enforcing / Checking PBC on the read atoms.
        atoms = self.enforce_pbc(atoms)

        # Get the grid dimensions.
        if "grid_dimensions" in kwargs.keys():
            grid_dimensions = kwargs["grid_dimensions"]

            # Deleting this keyword from the list to avoid conflict with
            # dict below.
            del kwargs["grid_dimensions"]
        else:
            qe_outfile = open(qe_out_file, "r")
            lines = qe_outfile.readlines()
            grid_dimensions = [0, 0, 0]

            for line in lines:
                if "FFT dimensions" in line:
                    tmp = line.split("(")[1].split(")")[0]
                    grid_dimensions[0] = int(tmp.split(",")[0])
                    grid_dimensions[1] = int(tmp.split(",")[1])
                    grid_dimensions[2] = int(tmp.split(",")[2])
                    break

        return self._calculate(atoms,
                               working_directory, grid_dimensions, **kwargs)

    def calculate_from_atoms(self, atoms, grid_dimensions,
                             working_directory=".", **kwargs):
        """
        Calculate the bispectrum descriptors based on atomic configurations.

        Parameters
        ----------
        atoms : ase.Atoms
            Atoms object holding the atomic configuration.

        grid_dimensions : list
            Grid dimensions to be used, in the format [x,y,z].

        working_directory : string
            A directory in which to write the output of the LAMMPS calculation.
            Usually the local directory should suffice, given that there
            are no multiple instances running in the same directory.

        Returns
        -------
        descriptors : numpy.array
            Numpy array containing the descriptors with the dimension
            (x,y,z,descriptor_dimension)
        """
        # Enforcing / Checking PBC on the input atoms.
        atoms = self.enforce_pbc(atoms)
        return self._calculate(atoms, working_directory,
                               grid_dimensions, **kwargs)

    def gather_descriptors(self, snap_descriptors_np, use_pickled_comm=False):
        """
        Gathers all bispectrum descriptors on rank 0 and sorts them.

        This is useful for e.g. parallel preprocessing.
        This function removes the extra 3 components that come from parallel
        processing.
        I.e. if we have 91 bispectrum descriptors, LAMMPS directly outputs us
        97 (in parallel mode), and this function returns 94, as to retain the
        3 x,y,z ones we by default include.

        Parameters
        ----------
        snap_descriptors_np : numpy.array
            Numpy array with the descriptors of this ranks local grid.

        use_pickled_comm : bool
            If True, the pickled communication route from mpi4py is used.
            If False, a Recv/Sendv combination is used. I am not entirely
            sure what is faster. Technically Recv/Sendv should be faster,
            but I doubt my implementation is all that optimal. For the pickled
            route we can use gather(), which should be fairly quick.
            However, for large grids, one CANNOT use the pickled route;
            too large python objects will break it. Therefore, I am setting
            the Recv/Sendv route as default.
        """
        # Barrier to make sure all ranks have descriptors..
        comm = get_comm()
        barrier()

        # Gather the descriptors into a list.
        if use_pickled_comm:
            all_descriptors_list = comm.gather(snap_descriptors_np,
                                                    root=0)
        else:
            sendcounts = np.array(comm.gather(np.shape(snap_descriptors_np)[0],
                                              root=0))
            raw_feature_length = self.fingerprint_length+3

            if get_rank() == 0:
                # print("sendcounts: {}, total: {}".format(sendcounts,
                #                                          sum(sendcounts)))

                # Preparing the list of buffers.
                all_descriptors_list = []
                for i in range(0, get_size()):
                    all_descriptors_list.append(
                        np.empty(sendcounts[i] * raw_feature_length,
                                 dtype=np.float64))

                # No MPI necessary for first rank. For all the others,
                # collect the buffers.
                all_descriptors_list[0] = snap_descriptors_np
                for i in range(1, get_size()):
                    comm.Recv(all_descriptors_list[i], source=i,
                              tag=100+i)
                    all_descriptors_list[i] = \
                        np.reshape(all_descriptors_list[i],
                                   (sendcounts[i], raw_feature_length))
            else:
                comm.Send(snap_descriptors_np, dest=0, tag=get_rank()+100)
            barrier()

        # if get_rank() == 0:
        #     printout(np.shape(all_descriptors_list[0]))
        #     printout(np.shape(all_descriptors_list[1]))
        #     printout(np.shape(all_descriptors_list[2]))
        #     printout(np.shape(all_descriptors_list[3]))

        # Dummy for the other ranks.
        # (For now, might later simply broadcast to other ranks).
        descriptors_full = np.zeros([1, 1, 1, 1])

        # Reorder the list.
        if get_rank() == 0:
            # Prepare the descriptor array.
            nx = self.grid_dimensions[0]
            ny = self.grid_dimensions[1]
            nz = self.grid_dimensions[2]
            descriptors_full = np.zeros(
                [nx, ny, nz, self.fingerprint_length])
            # Fill the full SNAP descriptors array.
            for idx, local_grid in enumerate(all_descriptors_list):
                # We glue the individual cells back together, and transpose.
                first_x = int(local_grid[0][0])
                first_y = int(local_grid[0][1])
                first_z = int(local_grid[0][2])
                last_x = int(local_grid[-1][0])+1
                last_y = int(local_grid[-1][1])+1
                last_z = int(local_grid[-1][2])+1
                descriptors_full[first_x:last_x,
                                 first_y:last_y,
                                 first_z:last_z] = \
                    np.reshape(local_grid[:, 3:],
                               [last_z-first_z, last_y-first_y, last_x-first_x,
                                self.fingerprint_length]).\
                    transpose([2, 1, 0, 3])

                # Leaving this in here for debugging purposes.
                # This is the slow way to reshape the descriptors.
                # for entry in local_grid:
                #     x = int(entry[0])
                #     y = int(entry[1])
                #     z = int(entry[2])
                #     descriptors_full[x, y, z] = entry[3:]
        if self.parameters.descriptors_contain_xyz:
            return descriptors_full
        else:
            return descriptors_full[:, :, :, 3:]

    def get_acsd(self, descriptor_data, ldos_data):
        """
        Calculate the ACSD for given descriptors and LDOS data.

        ACSD stands for average cosine similarity distance and is a metric
        of how well the descriptors capture the local environment to a
        degree where similar vectors result in simlar LDOS vectors.

        Parameters
        ----------
        descriptor_data : numpy.ndarray
            Array containing the descriptors.

        ldos_data : numpy.ndarray
            Array containing the LDOS.

        Returns
        -------
        acsd : float
            The average cosine similarity distance.

        """
        return self._calculate_acsd(descriptor_data, ldos_data,
                                    self.parameters.acsd_points,
                                    descriptor_vectors_contain_xyz=
                                    self.descriptors_contain_xyz)

    def _setup_lammps_processors(self, nx, ny, nz):
        """
        Set up the lammps processor grid.

        Takes into account y/z-splitting.
        """
        if self.parameters._configuration["mpi"]:
            size = get_size()
            # for parallel tem need to set lammps commands: processors and
            # balance current implementation is to match lammps mpi processor
            # grid to QE processor splitting QE distributes grid points in
            # parallel as slices along z axis currently grid points fall on z
            # axix plane cutoff values in lammps this leads to some ranks
            # having 0 grid points and other having 2x gridpoints
            # balance command in lammps aleviates this issue
            # integers for plane cuts in z axis appear to be most important
            #
            # determine if nyfft flag is set so that QE also parallelizes
            # along y axis if nyfft is true lammps mpi processor grid needs to
            # be 1x{ny}x{nz} need to configure separate total_energy_module
            # with nyfft enabled
            if self.parameters.use_y_splitting > 1:
                # TODO automatically pass nyfft into QE from MALA
                # if more processors thatn y*z grid dimensions requested
                # send error. More processors than y*z grid dimensions reduces
                # efficiency and scaling of QE.
                nyfft = self.parameters.use_y_splitting
                # number of y processors is equal to nyfft
                yprocs = nyfft
                # number of z processors is equal to total processors/nyfft is
                # nyfft is used else zprocs = size
                if size % yprocs == 0:
                    zprocs = int(size/yprocs)
                else:
                    raise ValueError("Cannot evenly divide z-planes "
                                     "in y-direction")

                # check if total number of processors is greater than number of
                # grid sections produce error if number of processors is
                # greater than grid partions - will cause mismatch later in QE
                mpi_grid_sections = yprocs*zprocs
                if mpi_grid_sections < size:
                    raise ValueError("More processors than grid sections. "
                                     "This will cause a crash further in the "
                                     "calculation. Choose a total number of "
                                     "processors equal to or less than the "
                                     "total number of grid sections requsted "
                                     "for the calculation (nyfft*nz).")
                # TODO not sure what happens when size/nyfft is not integer -
                #  further testing required

                # set the mpi processor grid for lammps
                lammps_procs = f"1 {yprocs} {zprocs}"
                printout("mpi grid with nyfft: ", lammps_procs,
                         min_verbosity=2)

                # prepare y plane cuts for balance command in lammps if not
                # integer value
                if int(ny / yprocs) == (ny / yprocs):
                    ycut = 1/yprocs
                    yint = ''
                    for i in range(0, yprocs-1):
                        yvals = ((i+1)*ycut)-0.00000001
                        yint += format(yvals, ".8f")
                        yint += ' '
                else:
                    # account for remainder with uneven number of
                    # planes/processors
                    ycut = 1/yprocs
                    yrem = ny - (yprocs*int(ny/yprocs))
                    yint = ''
                    for i in range(0, yrem):
                        yvals = (((i+1)*2)*ycut)-0.00000001
                        yint += format(yvals, ".8f")
                        yint += ' '
                    for i in range(yrem, yprocs-1):
                        yvals = ((i+1+yrem)*ycut)-0.00000001
                        yint += format(yvals, ".8f")
                        yint += ' '
                # prepare z plane cuts for balance command in lammps
                if int(nz / zprocs) == (nz / zprocs):
                    zcut = 1/nz
                    zint = ''
                    for i in range(0, zprocs-1):
                        zvals = ((i + 1) * (nz / zprocs) * zcut) - 0.00000001
                        zint += format(zvals, ".8f")
                        zint += ' '
                else:
                    # account for remainder with uneven number of
                    # planes/processors
                    raise ValueError("Cannot divide z-planes on processors"
                                     " without remainder. "
                                     "This is currently unsupported.")

                    # zcut = 1/nz
                    # zrem = nz - (zprocs*int(nz/zprocs))
                    # zint = ''
                    # for i in range(0, zrem):
                    #     zvals = (((i+1)*2)*zcut)-0.00000001
                    #     zint += format(zvals, ".8f")
                    #     zint += ' '
                    # for i in range(zrem, zprocs-1):
                    #     zvals = ((i+1+zrem)*zcut)-0.00000001
                    #     zint += format(zvals, ".8f")
                    #     zint += ' '
                lammps_dict = {"lammps_procs": f"processors {lammps_procs} "
                                               f"map xyz",
                               "zbal": f"balance 1.0 y {yint} z {zint}",
                               "ngridx": nx,
                               "ngridy": ny,
                               "ngridz": nz,
                               "switch": self.parameters.bispectrum_switchflag}
            else:
                if self.parameters.use_z_splitting:
                    # when nyfft is not used only split processors along z axis
                    size = get_size()
                    zprocs = size
                    # check to make sure number of z planes is not less than
                    # processors. If more processors than planes calculation
                    # efficiency decreases
                    if nz < size:
                        raise ValueError("More processors than grid sections. "
                                         "This will cause a crash further in "
                                         "the calculation. Choose a total "
                                         "number of processors equal to or "
                                         "less than the total number of grid "
                                         "sections requsted for the "
                                         "calculation (nz).")

                    # match lammps mpi grid to be 1x1x{zprocs}
                    lammps_procs = f"1 1 {zprocs}"
                    # print("mpi grid z only: ", lammps_procs)

                    # prepare z plane cuts for balance command in lammps
                    if int(nz / zprocs) == (nz / zprocs):
                        printout("No remainder in z")
                        zcut = 1/nz
                        zint = ''
                        for i in range(0, zprocs-1):
                            zvals = ((i+1)*(nz/zprocs)*zcut)-0.00000001
                            zint += format(zvals, ".8f")
                            zint += ' '
                    else:
                        #raise ValueError("Cannot divide z-planes on processors"
                        #                 " without remainder. "
                        #                 "This is currently unsupported.")
                        zcut = 1/nz
                        zrem = nz - (zprocs*int(nz/zprocs))
                        zint = ''
                        for i in range(0, zrem):
                            zvals = (((i+1)*(int(nz/zprocs)+1))*zcut)-0.00000001
                            zint += format(zvals, ".8f")
                            zint += ' '
                        for i in range(zrem, zprocs-1):
                            zvals = (((i+1)*int(nz/zprocs)+zrem)*zcut)-0.00000001
                            zint += format(zvals, ".8f")
                            zint += ' '
                    lammps_dict = {"lammps_procs":
                                   f"processors {lammps_procs}",
                                   "zbal": f"balance 1.0 z {zint}",
                                   "ngridx": nx,
                                   "ngridy": ny,
                                   "ngridz": nz,
                                   "switch": self.parameters.bispectrum_switchflag}
                else:
                    lammps_dict = {"ngridx": nx,
                                   "ngridy": ny,
                                   "ngridz": nz,
                                   "switch": self.parameters.bispectrum_switchflag}

        else:
            lammps_dict = {"ngridx": nx,
                           "ngridy": ny,
                           "ngridz": nz,
                           "switch": self.parameters.bispectrum_switchflag}
        return lammps_dict

    @staticmethod
    def _calculate_cosine_similarities(descriptor_data, ldos_data, nr_points,
                                       descriptor_vectors_contain_xyz=True):
        """
        Calculate the raw cosine similarities for descriptor and LDOS data.

        Parameters
        ----------
        descriptor_data : numpy.ndarray
            Array containing the descriptors.

        ldos_data : numpy.ndarray
            Array containing the LDOS.

        descriptor_vectors_contain_xyz : bool
            If true, the xyz values are cut from the beginning of the
            descriptor vectors.

        nr_points : int
            The number of points for which to calculate the ACSD.
            The actual number of distances will be acsd_points x acsd_points,
            since the cosine similarity is only defined for pairs.

        Returns
        -------
        similarity_array : numpy.ndarray
            A (2,nr_points*nr_points) array containing the cosine similarities.

        """
        def calc_cosine_similarity(vector1, vector2, norm=2):
            if np.shape(vector1)[0] != np.shape(vector2)[0]:
                raise Exception("Cannot calculate similarity between vectors "
                                "of different dimenstions.")
            if np.shape(vector1)[0] == 1:
                return np.min([vector1[0], vector2[0]]) / \
                       np.max([vector1[0], vector2[0]])
            else:
                return np.dot(vector1, vector2) / \
                       (np.linalg.norm(vector1, ord=norm) *
                        np.linalg.norm(vector2, ord=norm))

        descriptor_dim = np.shape(descriptor_data)
        ldos_dim = np.shape(ldos_data)
        if len(descriptor_dim) == 4:
            descriptor_data = np.reshape(descriptor_data,
                                         (descriptor_dim[0] *
                                          descriptor_dim[1] *
                                          descriptor_dim[2],
                                          descriptor_dim[3]))
            if descriptor_vectors_contain_xyz:
                descriptor_data = descriptor_data[:, 3:]
        elif len(descriptor_dim) != 2:
            raise Exception("Cannot work with this descriptor data.")

        if len(ldos_dim) == 4:
            ldos_data = np.reshape(ldos_data, (ldos_dim[0] * ldos_dim[1] *
                                               ldos_dim[2], ldos_dim[3]))
        elif len(ldos_dim) != 2:
            raise Exception("Cannot work with this LDOS data.")

        similarity_array = []
        # Draw nr_points at random from snapshot.
        rng = np.random.default_rng()
        points_i = rng.choice(np.shape(descriptor_data)[0],
                              size=np.shape(descriptor_data)[0],
                              replace=False)
        for i in range(0, nr_points):
            # Draw another nr_points at random from snapshot.
            rng = np.random.default_rng()
            points_j = rng.choice(np.shape(descriptor_data)[0],
                                  size=np.shape(descriptor_data)[0],
                                  replace=False)

            for j in range(0, nr_points):
                # Calculate similarities between these two pairs.
                descriptor_distance = \
                    calc_cosine_similarity(
                        descriptor_data[points_i[i]],
                        descriptor_data[points_j[j]])
                ldos_distance = calc_cosine_similarity(ldos_data[points_i[i]],
                                                       ldos_data[points_j[j]])
                similarity_array.append([descriptor_distance, ldos_distance])

        return np.array(similarity_array)

    @staticmethod
    def _calculate_acsd(descriptor_data, ldos_data, acsd_points,
                        descriptor_vectors_contain_xyz=True):
        """
        Calculate the ACSD for given descriptor and LDOS data.

        ACSD stands for average cosine similarity distance and is a metric
        of how well the descriptors capture the local environment to a
        degree where similar descriptor vectors result in simlar LDOS vectors.

        Parameters
        ----------
        descriptor_data : numpy.ndarray
            Array containing the descriptors.

        ldos_data : numpy.ndarray
            Array containing the LDOS.

        descriptor_vectors_contain_xyz : bool
            If true, the xyz values are cut from the beginning of the
            descriptor vectors.

        acsd_points : int
            The number of points for which to calculate the ACSD.
            The actual number of distances will be acsd_points x acsd_points,
            since the cosine similarity is only defined for pairs.

        Returns
        -------
        acsd : float
            The average cosine similarity distance.

        """
        def distance_between_points(x1, y1, x2, y2):
            return np.sqrt((x1 - x2) * (x1 - x2) + (y1 - y2) * (y1 - y2))

        similarity_data = Descriptor.\
            _calculate_cosine_similarities(descriptor_data, ldos_data,
                                           acsd_points,
                                           descriptor_vectors_contain_xyz=
                                           descriptor_vectors_contain_xyz)
        data_size = np.shape(similarity_data)[0]
        distances = []
        for i in range(0, data_size):
            distances.append(distance_between_points(similarity_data[i, 0],
                                                     similarity_data[i, 1],
                                                     similarity_data[i, 0],
                                                     similarity_data[i, 0]))
        return np.mean(distances)

    @abstractmethod
    def _calculate(self, atoms, outdir, grid_dimensions, **kwargs):
        pass
