#!/usr/bin/env python3
from numpy import ndarray, dot, arccos, pi, zeros, sqrt, log2, sum, isnan
from typing import List, Callable, Sequence
from argparse import Namespace
from numpy.linalg import norm
from numba import jit


# Location of the pool singleton.
_pool_singleton = None


@jit(nopython=True, nogil=True, target='cpu', parallel=True)
def _kl_divergence(p: ndarray, q: ndarray) -> float:
    """ TODO

    :param p:
    :param q:
    :return:
    """
    divergence = 0
    for v in p * log2(p / q):
        if not isnan(v):
            divergence += v
    return divergence


@jit(nopython=True, nogil=True, target='cpu', parallel=True)
def js_delta(sample_g: ndarray, observation: ndarray, bounds: ndarray) -> float:
    """ Given individuals from the simulated population and the frequencies of individuals from an observed sample,
    determine the differences in distribution for each different simulated sample. All vectors passed MUST be of
    appropriate size and must be zeroed out before use. We assume both vectors are always positive. Optimized by Numba.

    :param sample_g: Generated sample vector, which holds the sampled simulated population.
    :param observation: Observed frequency sample as a sparse frequency vector indexed by repeat length.
    :param bounds: Lower and upper bound (in that order) of the repeat unit space.
    :return: The distance between the generated and observed population.
    """
    kappa, omega = bounds  # Unpack our bounds.

    # Prepare the storage vector for our generated frequency vector.
    generated = zeros(omega - kappa + 1)

    # Fit the simulated population into a sparse vector of frequencies.
    for repeat_unit in range(kappa, omega + 1):
        ell_count = 0
        for ell in sample_g:  # Ugly code, but I'm trying to avoid dynamic memory allocation. ):
            ell_count += 1 if ell == repeat_unit else 0
        generated[repeat_unit - kappa] = ell_count / float(sample_g.size)

    m = 0.5 * (generated + observation)
    divergence = 0.5 * (_kl_divergence(generated, m) + _kl_divergence(observation, m))

    # Determine the Jensen-Shannon distance. 0 = identical, 1 = maximally dissimilar.
    return sqrt(divergence) if divergence > 0 else 1


@jit(nopython=True, nogil=True, target='cpu', parallel=True)
def cosine_delta(sample_g: ndarray, observation: ndarray, bounds: ndarray) -> float:
    """ Given individuals from the simulated population and the frequencies of individuals from an observed sample,
    determine the differences in distribution for each different simulated sample. All vectors passed MUST be of
    appropriate size and must be zeroed out before use. In order to transform this into a proper distance, we
    compute the angular cosine distance. We assume both vectors are always positive. Optimized by Numba.

    :param sample_g: Generated sample vector, which holds the sampled simulated population.
    :param observation: Observed frequency sample as a sparse frequency vector indexed by repeat length.
    :param bounds: Lower and upper bound (in that order) of the repeat unit space.
    :return: The distance between the generated and observed population.
    """
    kappa, omega = bounds  # Unpack our bounds.

    # Prepare the storage vector for our generated frequency vector.
    generated = zeros(omega - kappa + 1)

    # Fit the simulated population into a sparse vector of frequencies.
    for repeat_unit in range(kappa, omega + 1):
        ell_count = 0
        for ell in sample_g:  # Ugly code, but I'm trying to avoid dynamic memory allocation. ):
            ell_count += 1 if ell == repeat_unit else 0
        generated[repeat_unit - kappa] = ell_count / float(sample_g.size)

    # Determine the angular distance. 0 = identical, 1 = maximally dissimilar.
    return 2.0 * arccos(dot(generated, observation) / (norm(generated) * norm(observation))) / pi


@jit(nopython=True, nogil=True, target='cpu', parallel=True)
def euclidean_delta(sample_g: ndarray, observation: ndarray, bounds: ndarray) -> float:
    """ Given individuals from the simulated population and the frequencies of individuals from an observed sample,
    determine the differences in distribution for each different simulated sample. All vectors passed MUST be of
    appropriate size and must be zeroed out before use. Treating each distribution as a point, we compute the
    Euclidean distance between both points. Optimized by Numba.

    :param sample_g: Generated sample vector, which holds the sampled simulated population.
    :param observation: Observed frequency sample as a sparse frequency vector indexed by repeat length.
    :param bounds: Lower and upper bound (in that order) of the repeat unit space.
    :return: The distance between the generated and observed population.
    """
    kappa, omega = bounds  # Unpack our bounds.

    # Prepare the storage vector for our generated frequency vector.
    generated = zeros(omega - kappa + 1)

    # Fit the simulated population into a sparse vector of frequencies.
    for repeat_unit in range(kappa, omega + 1):
        ell_count = 0
        for ell in sample_g:  # Ugly code, but I'm trying to avoid dynamic memory allocation. ):
            ell_count += 1 if ell == repeat_unit else 0
        generated[repeat_unit - kappa] = ell_count / float(sample_g.size)

    # Determine the Euclidean distance. 0 = identical, 1 = maximally dissimilar.
    return norm(generated - observation)


def populate_d(d: ndarray, observations: Sequence, sample: Callable, delta: Callable, theta_proposed,
               bounds: Sequence) -> None:
    """ Compute the expected distance for all observations to a model generated by our proposed parameter set.

    :param d: D matrix to populate. Columns must match the length of observations. Rows indicate simulations.
    :param observations: 2D list of (int, float) tuples representing the (repeat length, frequency) tuples.
    :param sample: Function such that a population is produced with some parameter set and common ancestor.
    :param delta: Frequency distribution distance function. 0 = exact match, 1 = maximally dissimilar.
    :param theta_proposed: The parameters associated with this matrix instance.
    :param bounds: Upper and lower bound (in that order) of the repeat unit space.
    :return: None.
    """
    from kumulaau.observed import tuples_to_sparse_matrix
    from multiprocessing import Pool
    from numpy import array
    global _pool_singleton

    # We cannot compile this portion below, but we can parallelize it! Create a multiprocessing pool singleton.
    if _pool_singleton is None:
        _pool_singleton = Pool()

    # Generate all of our populations and save the generated data we are to compare to (bottleneck is here!!).
    sample_all = array(_pool_singleton.starmap(sample, [
        (theta_proposed, _choose_ell_0(observations, theta_proposed.kappa, theta_proposed.omega))
        for _ in range(d.shape[0])
    ]))

    # Generate the sparse matrix from our observations.
    sparse_matrix = tuples_to_sparse_matrix(observations, bounds)

    # Iterate through all generated samples.
    for i in range(d.shape[0]):
        for j in range(d.shape[1]):
            d[i, j] = delta(sample_all[i], sparse_matrix[j], array(bounds))


def _choose_ell_0(observations: Sequence, kappa: int, omega: int) -> List:
    """ We treat the starting repeat length ancestor as a nuisance parameter. We randomly choose a repeat length
    from our observed samples. If this choice exceeds our bounds, we choose our bounds instead.

    :param observations: 2D list of (int, float) tuples representing the (repeat length, frequency) tuples.
    :param kappa: Lower bound of our repeat length space.
    :param omega: Upper bound of our repeat length space.
    :return: A single repeat length, wrapped in a list.
    """
    from kumulaau.observed import tuples_to_pool
    from numpy.random import choice

    return [min(omega, max(kappa, choice(tuples_to_pool(observations))))]


def get_arguments() -> Namespace:
    """ Create the CLI and parse the arguments, if used as our main script.

    :return: Namespace of all values.
    """
    from argparse import ArgumentParser

    parser = ArgumentParser(description='Sample a simulated population and compare this to an observed data set.')
    list(map(lambda a: parser.add_argument(a[0], help=a[1], type=a[2], default=a[3], choices=a[4]), [
        ['-odb', 'Location of the observed database file.', str, 'data/observed.db', None],
        ['-function', 'Distance function to use.', str, None, ['cosine', 'euclidean', 'js']],
        ['-uid_observed', 'ID of the observed sample to compare to.', str, None, None],
        ['-locus_observed', 'Locus of the observed sample to compare to.', str, None, None]
    ]))

    return parser.parse_args()


if __name__ == '__main__':
    from kumulaau.observed import extract_alfred_tuples
    from timeit import default_timer as timer
    from kumulaau.model import trace, evolve
    from importlib import import_module
    from types import SimpleNamespace
    from numpy import array, mean, std

    arguments = get_arguments()  # Parse our arguments.

    # Collect observations to compare to.
    main_observed = extract_alfred_tuples([[arguments.uid_observed, arguments.locus_observed]], arguments.odb)

    # Determine our delta and sampling functions. Lambdas cannot be pickled, so we define a named function here.
    def main_sampler(theta, i_0):
        return evolve(trace(theta.n, theta.f, theta.c, theta.d, theta.kappa, theta.omega), i_0)
    main_delta_function = getattr(import_module('kumulaau.distance'), arguments.function + '_delta')

    # A quick and dirty function to generate and populate the HD matrices.
    def main_generate_and_fill_d():
        d = zeros((1000, len(main_observed)), dtype='float64')
        main_theta = SimpleNamespace(n=100, f=100.0, c=0.0001, d=0.00001, kappa=3, omega=30)
        populate_d(d, main_observed, main_sampler, main_delta_function, main_theta, [3, 30])
        return d

    # Run once to remove compile time in elapsed time.
    main_generate_and_fill_d()

    start_t = timer()
    main_d = main_generate_and_fill_d()  # Execute the sampling and print the running time.
    end_t = timer()
    print('Time Elapsed (1000x): [\n\t' + str(end_t - start_t) + '\n]')

    # Display our results to console, and record to our simulated database.
    print('Expected Distance: [\n\t' + str(mean(main_d)) + ' +/- ' + str(std(main_d)) + '\n]')
    print('End Matrix D: [\n\t' + str(main_d) + '\n]')
