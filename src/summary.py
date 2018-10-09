#!/usr/bin/env python3
from sqlite3 import Cursor
from typing import Iterable, List
from numpy.random import choice
from numpy.linalg import norm
from numpy import ndarray, dot
from numba import jit, prange
from abc import ABC, abstractmethod


def create_table(cur_j: Cursor) -> None:
    """ Create the table to log the results of our comparisons to.

    :param cur_j: Cursor to the database file to log to.
    :return: None.
    """
    cur_j.execute("""
        CREATE TABLE IF NOT EXISTS DELTA_POP (
            TIME_R TIMESTAMP,
            SIM_SAMPLE_ID TEXT,
            REAL_SAMPLE_UID TEXT,
            REAL_LOCUS TEXT,
            DELTA FLOAT
        );""")


def log_deltas(cur_j: Cursor, deltas: ndarray, osu: str, l: str) -> None:
    """ Given the computed differences between two sample's distributions, record each with a
    unique ID into the database.

    :param cur_j: Cursor to the database to log to.
    :param deltas: Computed differences from the sampling.
    :param osu: ID of the observed sample data set to compare to.
    :param l: Locus of the observed sample to compare to.
    :return: None.
    """
    from string import ascii_uppercase, digits
    from datetime import datetime
    from random import choice

    # Record our results.
    cur_j.executemany("""
        INSERT INTO DELTA_POP
        VALUES (?, ?, ?, ?, ?)
    """, ((datetime.now(), ''.join(choice(ascii_uppercase + digits) for _ in range(20)), osu, l, a)
          for a in deltas))


def population_from_count(ruc: Iterable) -> ndarray:
    """ Transform a list of repeat units and counts into a population of repeat units.

    :param ruc: List of lists, whose first element represents the repeat unit and second represents the count.
    :return: Population of repeat units.
    """
    from numpy import array

    ru = []
    for repeat_unit, c in ruc:
        ru = ru + [int(repeat_unit)] * c
    return array(ru)


class Compare(ABC):
    def __init__(self, srue: ndarray, two_n: int, r: int):
        """ Constructor. Store the population we are comparing to, the sample size, and the number of times to sample.

        :param srue: Simulated population of repeat units (one dimensional list).
        :param two_n: Sample size of the alleles.
        :param r: Number of times to sample the simulated population.
        """
        from numpy import array
        self.srue, self.two_n, self.r = srue, two_n, r

        # We will set the following fields upon preparation.
        self.scs, self.sfs, self.rfs, self.delta_rs = [array([]) for _ in range(4)]

    def _prepare(self, rfs_d: List) -> None:
        """ Given a "dirty" (non-length normalized) frequency vector of real samples, generate the appropriate
        vectors to store to.

        :param rfs_d: Dirty real frequency sample. Needs to be transformed into a sparse frequency vector.
        :return: None.
        """
        from numpy import zeros

        rfs_dict = {int(a[0]): float(a[1]) for a in rfs_d}  # Cast our real frequencies into numbers.

        # Determine the omega and kappa from the simulated effective population and our real sample.
        self.omega = max(self.srue) + 1 if max(self.srue) > max(rfs_dict.keys()) else max(rfs_dict.keys()) + 1
        self.kappa = min(self.srue) if min(self.srue) < min(rfs_dict.keys()) else min(rfs_dict.keys())

        # Create the vectors to return.
        self.scs, self.sfs, self.rfs, self.delta_rs = \
            [zeros(self.two_n), zeros(self.omega), zeros(self.omega), zeros(self.r)]

        # Fit our real distribution into a sparse frequency vector.
        for repeat_unit in rfs_dict.keys():
            self.rfs[repeat_unit] = rfs_dict[repeat_unit]

    @staticmethod
    @abstractmethod
    def _delta(scs: ndarray, sfs: ndarray, rfs: ndarray, srue: ndarray, delta_rs: ndarray, omega: int,
               kappa: int) -> None:
        """ Given individuals from the effective simulated population and the frequencies of individuals from a real
        sample, sample the same amount from the simulated population 'r' times and determine the differences in
        distribution for each different simulated sample. All vectors passed MUST be of appropriate size and must be
        zeroed out before use.

        :param scs: Storage vector, used to hold the sampled simulated population.
        :param sfs: Storage sparse vector, used to hold the frequency sample.
        :param rfs: Real frequency sample, represented as a sparse frequency vector indexed by repeat length.
        :param srue: Simulated population of repeat units (one dimensional list).
        :param delta_rs: Output vector, used to store the computed deltas of each sample.
        :param omega: Upper bound of the repeat unit space.
        :param kappa: Lower bound of the repeat unit space.
        """
        raise NotImplementedError

    def compute_delta(self, rfs_d: List) -> ndarray:
        """ Compute the deltas for 'r' samples, and return the results. For repeated runs of this function, we append
        our results to the same 'delta_rs' field.

        :param rfs_d: Dirty real frequency sample. Needs to be transformed into a sparse frequency vector.
        :return: The computed deltas for each sample.
        """
        from numpy import concatenate, array

        delta_rs_prev = array(self.delta_rs)  # Save our previous state. Prepare our SCS, SFS, RFS, and SRUE fields.
        self._prepare(rfs_d)

        # Run our sampling and comparison. Concatenate our previous state.
        self._delta(self.scs, self.sfs, self.rfs, self.srue, self.delta_rs, self.omega, self.kappa)
        self.delta_rs = concatenate((self.delta_rs, delta_rs_prev), axis=None)

        return self.delta_rs


class Frequency(Compare):
    def __init__(self, srue: ndarray, two_n: int, r: int):
        """ Constructor. Store the population we are comparing to, the sample size, and the number of times to sample.

        :param srue: Simulated population of repeat units (one dimensional list).
        :param two_n: Sample size of the alleles.
        :param r: Number of times to sample the simulated population.
        """
        super(Frequency, self).__init__(srue, two_n, r)
        raise DeprecationWarning  # Do not want to use this class for comparison... Cosine is better.

    @staticmethod
    @jit(nopython=True, nogil=True, target='cpu', parallel=True)
    def _delta(scs: ndarray, sfs: ndarray, rfs: ndarray, srue: ndarray, delta_rs: ndarray, omega: int,
               kappa: int) -> None:
        """ Given individuals from the effective simulated population and the frequencies of individuals from a real
        sample, sample the same amount from the simulated population 'r' times and determine the differences in
        distribution for each different simulated sample. All vectors passed MUST be of appropriate size and must be
        zeroed out before use. Optimized by Numba.

        :param scs: Storage vector, used to hold the sampled simulated population.
        :param sfs: Storage sparse vector, used to hold the frequency sample.
        :param rfs: Real frequency sample, represented as a sparse frequency vector indexed by repeat length.
        :param srue: Simulated population of repeat units (one dimensional list).
        :param delta_rs: Output vector, used to store the computed deltas of each sample.
        :param omega: Upper bound of the repeat unit space.
        :param kappa: Lower bound of the repeat unit space.
        :return: None.
        """
        for delta_k in prange(delta_rs.size):
            for k in prange(scs.size):  # Randomly sample n individuals from population.
                scs[k] = choice(srue)

            # Fit the simulated population into a sparse vector of frequencies.
            for repeat_unit in prange(kappa, omega):
                i_count = 0
                for i in scs:  # Ugly code, but I'm trying to avoid memory allocation. ):
                    i_count += 1 if i == repeat_unit else 0
                sfs[repeat_unit] = i_count / scs.size

            # For all repeat lengths, determine the sum difference in frequencies. Normalize this to [0, 1].
            delta_rs[delta_k] = 0
            for j in prange(kappa, omega):
                delta_rs[delta_k] += abs(sfs[j] - rfs[j])
            delta_rs[delta_k] = 1 - (delta_rs[delta_k] / 2.0)


class Cosine(Compare):
    @staticmethod
    @jit(nopython=True, nogil=True, target='cpu', parallel=True)
    def _delta(scs: ndarray, sfs: ndarray, rfs: ndarray, srue: ndarray, delta_rs: ndarray, omega: int,
               kappa: int) -> None:
        """ Given individuals from the effective simulated population and the frequencies of individuals from a real
        sample, sample the same amount from the simulated population 'r' times and determine the differences in
        distribution for each different simulated sample. All vectors passed MUST be of appropriate size and must be
        zeroed out before use. Optimized by Numba.

        :param scs: Storage vector, used to hold the sampled simulated population.
        :param sfs: Storage sparse vector, used to hold the frequency sample.
        :param rfs: Real frequency sample, represented as a sparse frequency vector indexed by repeat length.
        :param srue: Simulated population of repeat units (one dimensional list).
        :param delta_rs: Output vector, used to store the computed deltas of each sample.
        :param omega: Upper bound of the repeat unit space.
        :param kappa: Lower bound of the repeat unit space.
        :return: None.
        """
        for delta_k in prange(delta_rs.size):
            for k in prange(scs.size):  # Randomly sample n individuals from population.
                scs[k] = choice(srue)

            # Fit the simulated population into a sparse vector of frequencies.
            for repeat_unit in prange(kappa, omega):
                i_count = 0
                for i in scs:  # Ugly code, but I'm trying to avoid memory allocation. ):
                    i_count += 1 if i == repeat_unit else 0
                sfs[repeat_unit] = i_count / scs.size

            # For all repeat lengths, determine the sum difference in frequencies. Normalize this to [0, 1].
            delta_rs[delta_k] = (dot(sfs, rfs) / (norm(sfs) * norm(rfs)))


if __name__ == '__main__':
    from population import Population, BaseParameters
    from argparse import ArgumentParser
    from numpy import zeros, array
    from sqlite3 import connect

    parser = ArgumentParser(description='Sample a simulated population and compare this to a real data set.')
    parser.add_argument('-odb', help='Location of the observed database file.', type=str, default='data/observed.db')
    parser.add_argument('-ssdb', help='Location of the database to record data to.', type=str, default='data/delta.db')
    paa = lambda paa_1, paa_2, paa_3: parser.add_argument(paa_1, help=paa_2, type=paa_3)

    parser.add_argument('-f', help='Similarity index to use to compare.', type=str, choices=['COSINE', 'FREQ'])
    paa('-r', 'Number of times to sample the simulated population.', int)
    paa('-osu', 'ID of the observed sample data set to compare to.', str)
    paa('-l', 'Locus of the observed sample to compare to.', str)
    args = parser.parse_args()  # Parse our arguments.

    # Connect to all of our databases, and create our table if it does not already exist.
    conn_o, conn_ss = connect(args.odb), connect(args.ssdb)
    cur_o, cur_ss = conn_o.cursor(), conn_ss.cursor()
    create_table(cur_ss)

    freq_r = conn_o.execute(""" -- Pull the frequency distribution from the observed database. --
        SELECT ELL, ELL_FREQ
        FROM REAL_ELL
        WHERE SAMPLE_UID LIKE ?
        AND LOCUS LIKE ?
    """, (args.osu, args.l, )).fetchall()

    n_hat_m = int(conn_o.execute(""" -- Retrieve the sample size, the number of alleles. --
        SELECT SAMPLE_SIZE
        FROM REAL_ELL
        WHERE SAMPLE_UID LIKE ?
        AND LOCUS LIKE ?
    """, (args.osu, args.l, )).fetchone()[0])

    # Generate some population.
    z = Population(BaseParameters(n=100, f=1.0, c=0.01, u=0.001,
                                  d=0.001, kappa=3, omega=100)).evolve(array([11]))

    # Execute the sampling.
    end_deltas = None
    if args.f.casefold() == 'freq':
        end_deltas = Frequency(z, n_hat_m, args.r).compute_delta(freq_r)
    elif args.f.casefold() == 'cosine':
        end_deltas = Cosine(z, n_hat_m, args.r).compute_delta(freq_r)

    # Display our results to console, and record to our simulated database.
    print('Results: [\n\t' + ', '.join(str(a) for a in end_deltas) + '\n]')
    log_deltas(cur_ss, end_deltas, args.osu, args.l)
    conn_ss.commit(), conn_ss.close(), conn_o.close()