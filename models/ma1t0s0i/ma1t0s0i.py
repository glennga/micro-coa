#!/usr/bin/env python3
from numpy import nextafter, ndarray
from argparse import Namespace
from typing import Sequence
from kumulaau import *

# The model name associated with the results database.
MODEL_NAME = "MA1T0S0I"

# The model SQL associated with model database.
MODEL_SQL = "N INT, F FLOAT, C FLOAT, D FLOAT, KAPPA INT, OMEGA INT"


class Parameter1T0S0I(Parameter):
    def __init__(self, n: int, f: float, c: float, d: float, kappa: int, omega: int):
        """ Constructor. Here we set our parameters.

        :param n: Population size, used for determining the number of generations between events.
        :param f: Scaling factor for the total mutation rate. Smaller = shorter time to coalescence.
        :param c: Constant bias for the upward mutation rate.
        :param d: Linear bias for the downward mutation rate.
        :param kappa: Lower bound of repeat lengths.
        :param omega: Upper bound of repeat lengths.
        """
        super().__init__(n=n, f=f, c=c, d=d, kappa=kappa, omega=omega)

    def validity(self) -> bool:  # TODO: In the redesign, I don't think is being used... Verify this.
        """ Determine if a current parameter set is valid.

        :return: True if valid. False otherwise.
        """
        return self.n > 0 and \
            self.f >= 0 and \
            self.c > 0 and \
            self.d >= 0 and \
            0 < self.kappa < self.omega


def sample_1T0S0I(theta: Parameter1T0S0I, i_0: Sequence) -> ndarray:
    """ Generate a list of lengths of our 1T (one total) 0S (zero splits) 0I (zero intermediates) model.

    :param theta: Parameter1T0S0I set to use with tree tracing.
    :param i_0: Seed lengths associated with tree.
    :return: List of repeat lengths.
    """
    return model.evolve(model.trace(theta.n, theta.f, theta.c, theta.d, theta.kappa, theta.omega), i_0)


@Parameter1T0S0I.walkfunction
def walk_1T0S0I(theta, walk_params) -> Parameter1T0S0I:
    """ Given some parameter set theta and some distribution parameters, generate a new parameter set.

    :param theta: Current point to walk from.
    :param walk_params: Parameters associated with a walk.
    :return: A new parameter set.
    """
    from numpy.random import normal

    return Parameter1T0S0I(n=max(round(normal(theta.n, walk_params.n)), 0),
                           f=max(normal(theta.f, walk_params.f), 0),
                           c=max(normal(theta.c, walk_params.c), nextafter(0, 1)),
                           d=max(normal(theta.d, walk_params.d), 0),
                           kappa=max(round(normal(theta.kappa, walk_params.kappa)), 0),
                           omega=max(round(normal(theta.omega, walk_params.omega)), theta.kappa))


def get_arguments() -> Namespace:
    """ Create the CLI and parse the arguments.

    :return: Namespace of all values.
    """
    from argparse import ArgumentParser

    parser = ArgumentParser(description='ABC MCMC for microsatellite mutation model 1T0S0I parameter estimation.')

    list(map(lambda a: parser.add_argument(a[0], help=a[1], type=a[2], nargs=a[3], default=a[4], choices=a[5]), [
        ['-odb', 'Location of the observed database file.', str, None, 'data/observed.db', None],
        ['-mdb', 'Location of the database to record to.', str, None, 'data/ma1t0s0i.db', None],
        ['-uid', 'IDs of observed samples to compare to.', str, '+', None, None],
        ['-loci', 'Loci of observed samples (must match with uid).', str, '+', None, None],
        ['-delta_f', 'Distance function to use.', str, None, None, ['cosine', 'euclidean']],
        ['-simulation_n', 'Number of simulations to use to obtain a distance.', int, None, None, None],
        ['-iterations_n', 'Number of iterations to run MCMC for.', int, None, None, None],
        ['-epsilon', "Maximum acceptance value for distance between [0, 1].", float, None, None, None],
        ['-flush_n', 'Number of iterations to run MCMC before flushing to disk.', int, None, None, None],
        ['-n', 'Starting sample size (population size).', int, None, None, None],
        ['-f', 'Scaling factor for total mutation rate.', float, None, None, None],
        ['-c', 'Constant bias for the upward mutation rate.', float, None, None, None],
        ['-d', 'Linear bias for the downward mutation rate.', float, None, None, None],
        ['-kappa', 'Lower bound of repeat lengths.', int, None, None, None],
        ['-omega', 'Upper bound of repeat lengths.', int, None, None, None],
        ['-n_sigma', 'Step size of n when changing parameters.', float, None, None, None],
        ['-f_sigma', 'Step size of f when changing parameters.', float, None, None, None],
        ['-c_sigma', 'Step size of c when changing parameters.', float, None, None, None],
        ['-d_sigma', 'Step size of d when changing parameters.', float, None, None, None],
        ['-kappa_sigma', 'Step size of kappa when changing parameters.', float, None, None, None],
        ['-omega_sigma', 'Step size of omega when changing parameters.', float, None, None, None]
    ]))

    return parser.parse_args()


if __name__ == '__main__':
    from importlib import import_module

    arguments = get_arguments()  # Parse our arguments.

    # Collect observations to compare to.
    observations = observed.extract_alfred_tuples(zip(arguments.uid, arguments.loci), arguments.odb)

    # Determine if we are continuing an MCMC run or starting a new one.
    is_new_run = arguments.n is not None

    # Connect to our results database.
    with RecordSQLite(arguments.mdb, MODEL_NAME, MODEL_SQL, kumulaau.mcmca.SQL, is_new_run) as lumberjack:

        # Record our observations.
        lumberjack.record_observed(observations, map(lambda a, b: a + b, arguments.uid, arguments.loci))

        # Construct the walk, distance, and log functions based on our given arguments.
        walk = lambda a: walk_1T0S0I(a, Parameter1T0S0I.from_namespace(arguments, lambda b: b + '_sigma'))
        delta = getattr(import_module('kumulaau.distance'), arguments.delta_f + '_delta')
        log = lambda a, b: lumberjack.handler(a, b, arguments.flush_n)

        # Determine our starting point and boundaries.
        if arguments.n is not None:
            theta_0 = Parameter1T0S0I.from_namespace(arguments)
            boundaries = [0, arguments.iterations_n]
        else:
            theta_0 = Parameter1T0S0I(**lumberjack.retrieve_last_theta())
            offset = lumberjack.retrieve_last_result('PROPOSED_TIME')
            boundaries = [0 + offset, arguments.iterations_n + offset]

        # Run our MCMC!
        kumulaau.mcmca.run(walk=walk, sample=sample_1T0S0I, delta=delta, log_handler=log,
                           theta_0=theta_0, observed=observations, epsilon=arguments.epsilon, boundaries=boundaries)
