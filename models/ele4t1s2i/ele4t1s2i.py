#!/usr/bin/env python3
from argparse import Namespace
from numpy import ndarray
from kumulaau import *

# The model name associated with the results database.
MODEL_NAME = "ELE4T1S2I"

# The model SQL associated with model database.
MODEL_SQL = "I_0 INT, N_B INT, N_S1 INT, N_S2 INT, N_E INT, " \
            "F_B FLOAT, F_S1 FLOAT, F_S2 FLOAT, F_E FLOAT " \
            "ALPHA FLOAT, C FLOAT, D FLOAT, KAPPA INT, OMEGA INT"


class Parameter4T1S2I(Parameter):
    def __init__(self, i_0: int, n_b: int, n_s1: int, n_s2: int, n_e: int, f_b: float, f_s1: float, f_s2: float,
                 f_e: float, alpha: float, c: float, d: float, kappa: int, omega: int):
        """ Constructor. This is just meant to be a data class for the 4T1S2I model.

        :param i_0: Common ancestor repeat length (where to start mutating from).
        :param n_b: Population size of common ancestor population.
        :param n_s1: Population size of common ancestor descendant one.
        :param n_s2: Population size of common ancestor descendant two.
        :param f_b: Scaling factor for common ancestor population.
        :param f_s1: Scaling factor of common ancestor descendant one.
        :param f_s2: Scaling factor of common ancestor descendant two.
        :param f_e: Scaling factor of end population.
        :param alpha: Admixture constant of common ancestor descendant one.
        :param c: Constant bias for the upward mutation rate.
        :param d: Linear bias for the downward mutation rate.
        :param kappa: Lower bound of repeat lengths.
        :param omega: Upper bound of repeat lengths.
        """
        self.n_b, self.n_s1, self.n_s2, self.n_e, self.f_b, self.f_s1, self.f_s2, self.f_e, self.alpha = \
            round(n_b), round(n_s1), round(n_s2), round(n_e), f_b, f_s1, f_s2, f_e, alpha

        super().__init__(i_0, c, d, kappa, omega)

    def validity(self) -> bool:
        """ Determine if a current parameter set is valid. We constrain the following:

        1. A population size is always positive.
        2. Scaling parameters are always greater than / equal to zero.
        3. Mutation model parameters are never negative.
        4. Kappa (our lower bound) is between 0 and our upper bound, omega.
        5. Our admixture parameter is always between 0 and 0.5, prevent symmetry between split.
        6. n_e < n_s1 + n_s2 < n_e (we cannot have detached common ancestors).

        :return: True if valid. False otherwise.
        """
        return self.n_b > 0 and self.n_s1 > 0 and self.n_s2 > 0 and self.n_e > 0 and \
            self.f_b >= 0 and self.f_s1 >= 0 and self.f_s2 >= 0 and self.f_e >= 0 and \
            self.c > 0 and self.d >= 0 and \
            0 < self.kappa <= self.i_0 <= self.omega and \
            0 < self.alpha < 0.5 and \
            self.n_b < self.n_s1 + self.n_s2 < self.n_e


def sample_4T1S2I(theta: Parameter4T1S2I) -> ndarray:
    """ Generate a list of lengths of our 4T (four total) 1S (one splits) 2I (two intermediates) model.

    :param theta: Parameter4T1S2I set to use with tree tracing.
    :return: List of repeat lengths.
    """
    from numpy.random import normal, shuffle
    from numpy import concatenate

    # Create and evolve our common ancestor tree.
    common_ancestors = model.evolve(
        model.trace(theta.n_b, theta.f_b, theta.c, theta.d, theta.kappa, theta.omega),
        theta.i_0
    )

    # Determine our descendant inputs. Normally distributed around alpha.
    split_alpha = int(round(abs(normal(theta.alpha, 0.2)) * len(common_ancestors)))
    shuffle(common_ancestors)

    # Create the topology for our intermediate populations.
    descendant_1_top = model.trace(theta.n_s1, theta.f_s1, theta.c, theta.d, theta.kappa, theta.omega)
    descendant_2_top = model.trace(theta.n_s2, theta.f_s2, theta.c, theta.d, theta.kappa, theta.omega)

    # Evolve our intermediate populations.
    descendant_1 = model.evolve(descendant_1_top, common_ancestors[0:split_alpha])
    descendant_2 = model.evolve(descendant_2_top, common_ancestors[:-split_alpha])

    # Create the topology for our end population.
    end_top = model.trace(theta.n_e, theta.f_e, theta.c, theta.d, theta.kappa, theta.omega)

    # Evolve and return our end population.
    return model.evolve(end_top, concatenate((descendant_1, descendant_2)))


@Parameter4T1S2I.walkfunction
def walk_4T1S2I(theta, walk_params) -> Parameter4T1S2I:
    """ Given some parameter set theta and some distribution parameters, generate a new parameter set.

    :param theta: Current point to walk from.
    :param walk_params: Parameters associated with a walk.
    :return: A new parameter set.
    """
    from numpy.random import normal

    # Generate our population sizes for S_1 and S_2.
    n_s1 = round(normal(theta.n_s1, walk_params.n_s1))
    n_s2 = round(normal(theta.n_s2, walk_params.n_s2))

    # Our scaling factors must match between S_1 and S_2.
    f_s1 = normal(theta.f_s1, walk_params.f_s1)
    f_s2 = (n_s1 * f_s1) / n_s2 if n_s2 > 0 else 0  # Avoid DBZ error, decorator will generate new parameters anyway.

    # Draw from multivariate normal distribution for the rest.
    return Parameter4T1S2I(i_0=round(normal(theta.i_0, walk_params.i_0)),
                           n_b=round(normal(theta.n_b, walk_params.n_b)),
                           n_s1=n_s1, n_s2=n_s2,
                           n_e=round(normal(theta.n_e, walk_params.n_e)),
                           f_b=normal(theta.f_b, walk_params.f_b),
                           f_s1=f_s1, f_s2=f_s2,
                           f_e=normal(theta.f_e, walk_params.f_e),
                           alpha=normal(theta.alpha, walk_params.alpha),
                           c=normal(theta.c, walk_params.c),
                           d=normal(theta.d, walk_params.d),
                           kappa=round(normal(theta.kappa, walk_params.kappa)),
                           omega=round(normal(theta.omega, walk_params.omega)))


def get_arguments() -> Namespace:
    """ Create the CLI and parse the arguments.

    :return: Namespace of all values.
    """
    from argparse import ArgumentParser

    parser = ArgumentParser(description='ELE MCMC for microsatellite mutation model 4T1S2I parameter estimation.')

    list(map(lambda a: parser.add_argument(a[0], help=a[1], type=a[2], nargs=a[3], default=a[4], choices=a[5]), [
        ['-mdb', 'Location of the database to record to.', str, None, 'data/abc1t0s0i.db', None],
        ['-observations', 'String of tuple representation of observations.', str, None, None, None],
        ['-delta', 'Distance function to use.', str, None, None, ['cosine', 'euclidean']],
        ['-simulation_n', 'Number of simulations to use to obtain a distance.', int, None, None, None],
        ['-iterations_n', 'Number of iterations to run MCMC for.', int, None, None, None],
        ['-r', "Exponential decay rate for weight vector used in regression (a=1).", float, None, None, None],
        ['-bin_n', "Number of bins used to construct histogram.", int, None, None, None],
        ['-flush_n', 'Number of iterations to run MCMC before flushing to disk.', int, None, None, None],
        ['-i_0_start', 'Starting ancestor repeat length.', int, None, None, None],
        ['-n_b_start', 'Population size for common ancestor.', int, None, None, None],
        ['-n_s1_start', 'Population size for intermediate 1.', int, None, None, None],
        ['-n_s2_start', 'Population size for intermediate 2.', int, None, None, None],
        ['-n_e_start', 'Population size for end population.', int, None, None, None],
        ['-f_b_start', 'Scaling factor for common ancestor mutation rate.', float, None, None, None],
        ['-f_s1_start', 'Scaling factor for intermediate 1 mutation rate.', float, None, None, None],
        ['-f_s2_start', 'Scaling factor for intermediate 2 mutation rate.', float, None, None, None],
        ['-f_e_start', 'Scaling factor for end population mutation rate.', float, None, None, None],
        ['-alpha_start', 'Admixture factor between S1 and S2, between [0, 1].', float, None, None, None],
        ['-c_start', 'Constant bias for the upward mutation rate.', float, None, None, None],
        ['-d_start', 'Linear bias for the downward mutation rate.', float, None, None, None],
        ['-kappa_start', 'Lower bound of repeat lengths.', int, None, None, None],
        ['-omega_start', 'Upper bound of repeat lengths.', int, None, None, None],
        ['-i_0_sigma', 'Step size of i_0 when changing parameters.', float, None, None, None],
        ['-n_b_sigma', 'Step size of n_b when changing parameters.', float, None, None, None],
        ['-n_s1_sigma', 'Step size of n_s1 when changing parameters.', float, None, None, None],
        ['-n_s2_sigma', 'Step size of n_s2 when changing parameters.', float, None, None, None],
        ['-n_e_sigma', 'Step size of n_e when changing parameters.', float, None, None, None],
        ['-f_b_sigma', 'Step size of f_b when changing parameters.', float, None, None, None],
        ['-f_s1_sigma', 'Step size of f_s1 when changing parameters.', float, None, None, None],
        ['-f_s2_sigma', '*Unused*.', float, None, 0.0, None],  # Required for 'from_namespace' to work.
        ['-f_e_sigma', 'Step size of f_e when changing parameters.', float, None, None, None],
        ['-alpha_sigma', 'Step size of alpha when changing parameters', float, None, None, None],
        ['-c_sigma', 'Step size of c when changing parameters.', float, None, None, None],
        ['-d_sigma', 'Step size of d when changing parameters.', float, None, None, None],
        ['-kappa_sigma', 'Step size of kappa when changing parameters.', float, None, None, None],
        ['-omega_sigma', 'Step size of omega when changing parameters.', float, None, None, None]
    ]))

    return parser.parse_args()


if __name__ == '__main__':
    from importlib import import_module
    from ast import literal_eval

    arguments = get_arguments()  # Parse our arguments.
    observations = literal_eval(arguments.observations)

    # Determine if we are continuing an MCMC run or starting a new one.
    is_new_run = arguments.n_b_start is not None

    # Connect to our results database.
    with RecordSQLite(arguments.mdb, MODEL_NAME, MODEL_SQL, is_new_run) as lumberjack:

        if is_new_run:  # Record our observations and experiment parameters.
            lumberjack.record_observed(observations)
            lumberjack.record_expr(list(vars(arguments).keys()), list(vars(arguments).values()))

        # Construct the walk, summary, and log functions based on our given arguments.
        walk = lambda a: walk_4T1S2I(a, Parameter4T1S2I.from_namespace(arguments, lambda b: b + '_sigma'))
        log = lumberjack.handler_factory(arguments.flush_n)
        delta = getattr(import_module('kumulaau.distance'), arguments.delta + '_delta')

        # Determine our starting point and boundaries.
        if is_new_run:
            theta_0 = Parameter4T1S2I.from_namespace(arguments, lambda a: a + '_start')
            boundaries = [0, arguments.iterations_n]
        else:
            theta_0 = Parameter4T1S2I(**lumberjack.retrieve_last_theta())
            offset = lumberjack.retrieve_last_result('PROPOSED_TIME')
            boundaries = [0 + offset, arguments.iterations_n + offset]

        # Run our MCMC!
        kumulaau.ele.run(walk=walk, sample=sample_4T1S2I, delta=delta, log_handler=log,
                         theta_0=theta_0, observed=observations, simulation_n=arguments.simulation_n,
                         boundaries=boundaries, r=arguments.r, bin_n=arguments.bin_n)
