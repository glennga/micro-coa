#!/usr/bin/env python3
from single import ModelParameters
from numpy import ndarray
from sqlite3 import Cursor
from typing import List, Callable


def create_table(cur_j: Cursor) -> None:
    """ Create the table to log the results of our comparisons to.

    :param cur_j: Cursor to the database file to log to.
    :return: None.
    """
    cur_j.execute("""
        CREATE TABLE IF NOT EXISTS WAIT_POP (
            TIME_R TIMESTAMP,
            REAL_SAMPLE_UIDS TEXT,
            REAL_LOCI TEXT,
            EFF_ID TEXT,
            BIG_N INT,
            MU FLOAT,
            S FLOAT,
            KAPPA INT,
            OMEGA INT,
            U FLOAT,
            V FLOAT,
            M FLOAT,
            P FLOAT,
            WAITING INT,
            DELTA FLOAT,
            ACCEPTANCE_TIME INT
        );""")


def log_states(cur_j: Cursor, rsu: List[str], l: List[str], chain: List) -> None:
    """ Record our states to some database.

    :param cur_j: Cursor to the database file to log to.
    :param rsu: IDs of the real sample data sets to compare to.
    :param l: Loci of the real samples to compare to.
    :param chain: States and associated times & probabilities collected after running MCMC.
    :return: None.
    """
    from datetime import datetime

    # Generate our real sample log strings.
    rsu_log, l_log = list(map(lambda a: '-'.join(b for b in a), [rsu, l]))

    cur_j.executemany(f"""
            INSERT INTO WAIT_POP
            VALUES ({','.join('?' for _ in range(16))});
        """, ((datetime.now(), rsu_log, l_log, a[4], a[0].big_n, a[0].mu, a[0].s, a[0].kappa, a[0].omega,
               a[0].u, a[0].v, a[0].m, a[0].p, a[1], a[2], a[3]) for a in chain))


def choose_i_0(rfs: List) -> ndarray:
    """ We treat the starting population length ancestor as a nuisance parameter. We randomly choose a repeat length
    from our real samples.

    :param rfs: Real frequency samples. A list of: [first column is the length, second is the frequency].
    :return: A single repeat length, wrapped in a Numpy array.
    """
    from random import choice
    from numpy import array

    return array([int(choice(choice(rfs))[0])])


def mcmc(it: int, fc: str, rfs_d: List, r: int, two_n: List[int], theta_init: ModelParameters,
         theta_sigma: ModelParameters, acceptance_f: Callable) -> List:
    """ An MCMC algorithm to approximate the posterior distribution of the mutation model, whose acceptance to the
    chain is determined by some lambda. We start with some initial guess and simulate an entire population. We then
    compute the average distance between a set of simulated and real samples (delta). This is meant to be wrapped within
    another function to determine how the chain should be shaped.

    :param it: Number of iterations to run MCMC for.
    :param fc: Location of the folder to store all of our coalescence chains to.
    :param rfs_d: Dirty real frequency samples. A list of: [first column is the length, second is the frequency].
    :param r: Number of simulated samples to use to obtain delta.
    :param two_n: Sample sizes of the alleles. Must match the order of the real samples given here.
    :param theta_init: Our initial guess for parameters.
    :param theta_sigma: The deviations associated with all parameters to use when generating new parameters.
    :param acceptance_f: Some lambda that accepts the delta and the previous delta, and returns true/false.
    :return: A chain of all states we visited (parameters), their associated waiting times, and the sum total of their
             acceptance probabilities.
    """
    from numpy.random import normal
    from numpy import average
    from single import Single
    from compare import compare, prepare_compare
    from exhaust import log_coalescence

    states = [[theta_init, 1, 0.0000000001, 0, '']]  # Seed our chain with our initial guess.
    walk = lambda a, b, c=False: normal(a, b) if c is False else round(normal(a, b))

    for j in range(1, it):
        theta_prev = states[-1][0]  # Our current position in the state space. Walk from this point.
        theta_proposed = ModelParameters(i_0=choose_i_0(rfs_d), big_n=walk(theta_prev.big_n, theta_sigma.big_n, True),
                                         mu=walk(theta_prev.mu, theta_sigma.mu), s=walk(theta_prev.s, theta_sigma.s),
                                         kappa=walk(theta_prev.kappa, theta_sigma.kappa, True),
                                         omega=walk(theta_prev.omega, theta_sigma.omega, True),
                                         u=walk(theta_prev.u, theta_sigma.u), v=walk(theta_prev.v, theta_sigma.v),
                                         m=walk(theta_prev.m, theta_sigma.m), p=walk(theta_prev.p, theta_sigma.p))

        z_s = Single(theta_proposed)  # Generate some population given the current parameter set, and record this.
        z = Single(theta_proposed).evolve()

        summary_deltas = []  # Compute the delta term: the average probability using all available samples.
        for d in zip(rfs_d, two_n):
            scs, sfs, rfs, delta_rs = prepare_compare(d[0], z, d[1], r)
            compare(scs, sfs, rfs, z, delta_rs)  # Messy, but so is Numba. ):<
            summary_deltas = summary_deltas + [1 - average(delta_rs)]
        summary_delta = average(summary_deltas)

        # Accept our proposal according to the given function.
        if acceptance_f(summary_delta, states[-1][2]):
            states = states + [[theta_proposed, 1, summary_delta, j, log_coalescence(fc, z_s)]]

        # Reject our proposal. We keep our current state and increment our waiting times.
        else:
            states[-1][1] += 1

    return states[1:]


def abc(it: int, fc: str, rfs_d: List, r: int, two_n: List[int], epsilon: float, theta_init: ModelParameters,
        theta_sigma: ModelParameters) -> List:
    """ My interpretation of an MCMC-ABC rejection sampling approach to approximate the posterior distribution of the
    mutation model. We start with some initial guess and simulate an entire population. We then compute the
    average distance between a set of simulated and real samples (delta). If this term is above some defined epsilon,
    we append this to our chain. Otherwise, we reject it and increase the waiting time of our current parameter state
    by one. Source:

    https://theoreticalecology.wordpress.com/2012/07/15/a-simple-approximate-bayesian-computation-mcmc-abc-mcmc-in-r/

    :param it: Number of iterations to run MCMC for.
    :param fc: Location of the folder to store all of our coalescence chains to.
    :param rfs_d: Dirty real frequency samples. A list of: [first column is the length, second is the frequency].
    :param r: Number of simulated samples to use to obtain delta.
    :param two_n: Sample sizes of the alleles. Must match the order of the real samples given here.
    :param epsilon: Minimum acceptance value for delta.
    :param theta_init: Our initial guess for parameters.
    :param theta_sigma: The deviations associated with all parameters to use when generating new parameters.
    :return: A chain of all states we visited (parameters), their associated waiting times, and the sum total of their
             acceptance probabilities.
    """
    return mcmc(it, fc, rfs_d, r, two_n, theta_init, theta_sigma, lambda a, b: a > epsilon)


def mh(it: int, fc: str, rfs_d: List, r: int, two_n: List[int], theta_init: ModelParameters,
       theta_sigma: ModelParameters) -> List:
    """ My interpretation of an MCMC approach using metropolis hastings sampling to approximate the posterior
    distribution of the mutation model. We start with some initial guess and simulate an entire population. We then
    compute the acceptance probability (alpha) based on the proposed and the past states, and accept if some uniform
    random variable is less than alpha. Otherwise, we reject it and increase the waiting of our current parameter state
    (not proposed) by one. Source:

    https://advaitsarkar.wordpress.com/2014/03/02/the-metropolis-hastings-algorithm-tutorial/

    :param it: Number of iterations to run MCMC for.
    :param fc: Location of the folder to store all of our coalescence chains to.
    :param rfs_d: Dirty real frequency samples. A list of: [first column is the length, second is the frequency].
    :param r: Number of simulated samples to use to obtain delta.
    :param two_n: Sample sizes of the alleles. Must match the order of the real samples given here.
    :param theta_init: Our initial guess for parameters.
    :param theta_sigma: The deviations associated with all parameters to use when generating new parameters.
    :return: A chain of all states we visited (parameters), their associated waiting times, and the sum total of their
             acceptance probabilities.
    """
    from numpy.random import uniform

    return mcmc(it, fc, rfs_d, r, two_n, theta_init, theta_sigma, lambda a, b: min(1, a / b) > uniform(0, 1))


if __name__ == '__main__':
    from argparse import ArgumentParser
    from sqlite3 import connect
    from numpy import array

    parser = ArgumentParser(description='MCMC for microsatellite mutation parameter estimation.')
    parser.add_argument('-rdb', help='Location of the real database file.', type=str, default='data/real.db')
    parser.add_argument('-edb', help='Location of the database to record to.', type=str, default='data/posterior.db')
    parser.add_argument('-fc', help='Location of the folder to record populations to.', type=str, default='data')
    paa = lambda paa_1, paa_2, paa_3: parser.add_argument(paa_1, help=paa_2, type=paa_3)

    parser.add_argument('-rsu', help='IDs of real samples to compare to.', type=str, nargs='+')
    parser.add_argument('-l', help='Loci of real samples to compare to (must match with rsu).', type=str, nargs='+')
    parser.add_argument('-type', help='Type of MCMC to run.', type=str, choices=['ABC', 'MH'])
    paa('-r', 'Number of simulated samples to use to obtain delta.', int)
    paa('-epsilon', 'Minimum acceptance value for delta.', float)
    paa('-it', 'Number of iterations to run MCMC for.', int)

    paa('-big_n', 'Starting effective population size.', int)
    paa('-mu', 'Starting mutation rate, bounded by (0, infinity).', float)
    paa('-s', 'Starting proportional rate, bounded by (-1 / (omega - kappa + 1), infinity).', float)
    paa('-kappa', 'Starting lower bound of possible repeat lengths.', int)
    paa('-omega', 'Starting upper bounds of possible repeat lengths.', int)
    paa('-u', 'Starting constant bias parameter, bounded by [0, 1].', float)
    paa('-v', 'Starting linear bias parameter, bounded by (-infinity, infinity).', float)
    paa('-m', 'Starting success probability for truncated geometric distribution.', float)
    paa('-p', 'Starting probability that the repeat length change is +/- 1.', float)

    paa('-big_n_sigma', 'Step size of big_n when changing parameters.', float)
    paa('-mu_sigma', 'Step size of mu when changing parameters.', float)
    paa('-s_sigma', 'Step size of s when changing parameters.', float)
    paa('-kappa_sigma', 'Step size of kappa when changing parameters.', float)
    paa('-omega_sigma', 'Step size of omega when changing parameters.', float)
    paa('-u_sigma', 'Step size of u when changing parameters.', float)
    paa('-v_sigma', 'Step size of v when changing parameters.', float)
    paa('-m_sigma', 'Step size of m when changing parameters.', float)
    paa('-p_sigma', 'Step size of p when changing theta.', float)
    args = parser.parse_args()  # Parse our arguments.

    # Connect to all of our databases.
    conn_r, conn_e = connect(args.rdb), connect(args.edb)
    cur_r, cur_e = conn_r.cursor(), conn_e.cursor()
    create_table(cur_e)

    freq_r = list(map(lambda a, b: cur_r.execute(""" -- Pull the frequency distributions from the real database. --
        SELECT ELL, ELL_FREQ
        FROM REAL_ELL
        WHERE SAMPLE_UID LIKE ?
        AND LOCUS LIKE ?
      """, (a, b,)).fetchall(), args.rsu, args.l))

    two_nm = list(map(lambda a, b: int(cur_r.execute(""" -- Retrieve the sample sizes, the number of alleles. --
        SELECT SAMPLE_SIZE
        FROM REAL_ELL
        WHERE SAMPLE_UID LIKE ?
        AND LOCUS LIKE ?
    """, (a, b,)).fetchone()[0]), args.rsu, args.l))

    # Perform the MCMC, and record our chain.
    theta_0_m = ModelParameters(i_0=choose_i_0(freq_r), big_n=args.big_n, mu=args.mu, s=args.s, kappa=args.kappa,
                                omega=args.omega, u=args.u, v=args.v, m=args.m, p=args.p)
    theta_s_m = ModelParameters(i_0=choose_i_0(freq_r), big_n=args.big_n_sigma, mu=args.mu_sigma, s=args.s_sigma,
                                kappa=args.kappa_sigma, omega=args.omega_sigma, u=args.u_sigma, v=args.v_sigma,
                                m=args.m_sigma, p=args.p_sigma)

    if args.type.casefold() == 'ABC'.casefold():
        log_states(cur_e, args.rsu, args.l, abc(args.it, args.fc, freq_r, args.r, two_nm, args.epsilon, theta_0_m,
                                                theta_s_m))
    elif args.type.casefold() == 'MH'.casefold():
        log_states(cur_e, args.rsu, args.l, mh(args.it, args.fc, freq_r, args.r, two_nm, theta_0_m, theta_s_m))
    conn_e.commit(), conn_r.close(), conn_e.close()