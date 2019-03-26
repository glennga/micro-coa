#!/usr/bin/env python3
from kumulaau.distance import populate_d
from typing import Callable, Sequence
from numpy import ndarray

# The model SQL associated with model database.
SQL = 'TIME_R TIMESTAMP, WAITING_TIME INT, P_PROPOSED FLOAT, EXPECTED_DELTA FLOAT, PROPOSED_TIME INT'


def _generate_v(d: ndarray, r: float) -> ndarray:
    """ Populate the V vector, a collection of likelihoods found using the populated D matrix and our weighted linear
    regression likelihood approximator approach.

    :param d: **Populated** D matrix, holding all distances between a generated and observed population.
    :param r: Exponential decay rate for weight vector used in regression (a=1).
    :return: None.
    """
    from numpy import sort, log, zeros, fromiter, linspace, vstack, ones, exp
    from numpy.linalg import lstsq

    # Our resulting V vector.
    v = zeros(d.shape[1])

    # Generate our weights using an exponential decay function. We weigh distances closer to 0 more.
    domain = fromiter(linspace(0, 1, d.shape[0]), float, d.shape[0])  # Normalized to [0, 1].
    big_a = vstack([domain, ones(d.shape[0])]).T
    w = fromiter(map(lambda a: (1 - r)**a, domain), float, d.shape[0])

    # Iterate through our columns (w/ transpose of D).
    for i, distances in enumerate(d.T):
        cdf_log = log(sort(distances))  # We want this on the log scale.

        # Perform our regression. Intercept = the probability of an exact match with these set of distances.
        v[i] = lstsq(big_a, cdf_log * w, rcond=-1)[0][1]

    return exp(v)  # Convert back from log scale.


def _likelihood_from_v(v: ndarray) -> float:
    """ Each entry in v corresponds to the probability a model (parameters) match this observed sample. Taking the
    product gives us the likelihood (assumes each is independent).

    :param v: **Populated** v vector, holding all probabilities associated with a given observation.
    :return: The likelihood the generated sample set matches our observations.
    """
    from numpy import log, exp

    # Avoid floating point error, use logarithms. Avoid log(0) errors.
    return exp(sum(map(lambda a: 0 if a == 0 else log(a), v)))


def run(walk: Callable, sample: Callable, delta: Callable, log_handler: Callable, theta_0, observed: Sequence,
        r: float, boundaries: Sequence) -> None:
    """ Our approach: a weighted regression-based likelihood approximator using MCMC to walk around our posterior
    distribution. My interpretation of this approach is given below:

    1) We start with some initial guess theta_0. Right off the bat, we move to another theta from theta_0.
    2) For 'iterations_bounds[1] - iterations_bounds[0]' iterations...
        a) For 'simulation_n' iterations...
            i) We simulate a population using the given theta.
            ii) For each observed frequency ... 'D'
                1) We compute the difference between the two distributions.
                2) ** Apply our weighted regression likelihood approximator here. ** Obtain a probability.
        c) If this probability is greater than the probability of the previous, we accept.
        d) Otherwise, we accept our proposed with probability p(proposed) / p(prev).

    :param walk: Function that accepts some parameter set and returns another parameter set.
    :param sample: Function that produces a collection of repeat lengths (i.e. the model function).
    :param delta: Function that computes the distance between the result of a sample and an observation.
    :param log_handler: Function that handles what occurs with the current Markov chain and results.
    :param theta_0: Initial starting point.
    :param observed: 2D list of (int, float) tuples representing the (repeat length, frequency) tuples.
    :param r: Exponential decay rate for weight vector used in regression (a=1).
    :param boundaries: Starting and ending iteration for this specific MCMC run.
    :return: None.
    """
    from types import SimpleNamespace
    from numpy.random import uniform
    from datetime import datetime
    from numpy import zeros, mean

    # Save our results according to the namespace below.
    a_record = lambda a_1, b_1, c_1, d_1, e_1, f_1: SimpleNamespace(theta=a_1, time_r=b_1, waiting_time=c_1,
                                                                    p_proposed=d_1, expected_delta=e_1,
                                                                    proposed_time=f_1)

    # Seed our Markov chain with our initial guess.
    x = [a_record(theta_0, 0, 1, 1.0e-10, 1.0e-10, 0)]

    for i in range(boundaries[0] + 1, boundaries[1]):
        theta_proposed = walk(x[-1].theta)  # Walk from our previous state.

        # Generate our D matrix.
        d = zeros((boundaries[1] - boundaries[0], len(observed)), dtype='float64')
        populate_d(d, observed, sample, delta, theta_proposed, [theta_proposed.kappa, theta_proposed.omega])

        # Compute our likelihood vector.
        v = _generate_v(d, r)

        # Accept our proposal according to our alpha value.
        p_proposed, p_k = _likelihood_from_v(v), x[-1].p_proposed
        if p_proposed / p_k > uniform(0, 1):
            x = x + [a_record(theta_proposed, datetime.now(), 1, p_proposed, mean(d), i)]

        # Reject our proposal. We keep our current state and increment our waiting times.
        else:
            x[-1].waiting_time += 1

        # We record to our chain. This is dependent on the current iteration of MCMC.
        log_handler(x, i)
