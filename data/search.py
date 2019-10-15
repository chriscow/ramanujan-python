import os
import itertools
import time
from datetime import datetime
import logging
import mpmath
from mpmath import mpf, mpc
from redis import Redis
from rq import Queue
from rediscluster import RedisCluster

import algorithms
import config
import jobs
import postproc
import utils

import pickle

log = logging.getLogger(__name__)

from data.wrapper import HashtableWrapper

def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def run(max_precision=50, sync=False, silent=False):
    '''
    We want to:
        - make a first pass and find all key matches between the two sides
        - with all matches, 
    '''
    log.info(f'[search.run] max_precision:{max_precision} sync:{sync} silent:{silent} at {time.time()}')

    local_redis = Redis(db=os.getenv('WORK_QUEUE_DB'))
    q = Queue(connection=local_redis)
    log.debug(f'Localhost redis work queue is {os.getenv("WORK_QUEUE_DB")}')


    lhs_db = HashtableWrapper('lhs')
    rhs_db = HashtableWrapper('rhs')

    for lhs_keys in lhs_db.scan():

        if sync:
            jobs.queue_search(lhs_keys, sync)
        else:
            q.enqueue(jobs.queue_search, lhs_keys, sync)

    jobs.wait(0, 0, silent)
    print()


# def test():

#     log.debug(f'Waiting for remaining {len(work)} items to finish...')
#     jobs.wait(0, 0, silent)
#     for job in work:
#         if job.result:
#             matches |= job.result

#     # update redis with our search progress so we can pick up where we left off

#     if not silent:
#         utils.printProgressBar(100, 100)

#     log.info(f'Found {len(matches)} initial matches')

    # # 'matches()' contains the arguments where the values matched exactly
    # # at 15 decimal places (whatever is in the config)
    # #
    # # Now lets try matching more decimal places
    # bigger_matches = set()

    # redis_conn = Redis(host=os.getenv('REDIS_HOST') , db=os.getenv('WORK_QUEUE_DB'))
    # q = Queue(connection=redis_conn)

    # # Loop over and over, doubling the decimal precision until decimal places 
    # # exceeds 100 or until there are no more matches
    # while len(matches) and mpmath.mp.dps < max_precision:
    #     bigger_matches = set()

    #     mpmath.mp.dps *= 2  # increase the decimal precision

    #     # cap it if it exceeds the maximum requested
    #     if mpmath.mp.dps > max_precision:
    #         mpmath.mp.dps = max_precision

    #     count = 0 # for progress bar

    #     work = set()

    #     for lhs_val, rhs_val in matches:
            
    #         # # Since we want more precision, also expand the polynomial range 10x
    #         # # for the continued fraction (or whatever algorithm it used)
    #         # # for the right hand side
    #         lhs_val = eval(lhs_val)
    #         rhs_val = list(eval(rhs_val))
    #         poly_range = eval(rhs_val[3]) # unpack the range
    #         poly_range = (poly_range[0] * -10, poly_range[1] * 10) # expand it
    #         rhs_val[3] = bytes(repr(poly_range), 'utf-8') # re-pack the range

    #         # # solve both sides with the new precision
    #         # lhs = mpmath.fabs(jobs.reverse_solve(eval(lhs_val)))
    #         # rhs = mpmath.fabs(jobs.reverse_solve(rhs_algo))

    #         if debug:
    #             result = jobs.check_match(mpmath.mp.dps, repr(lhs_val), repr(rhs_val))
    #             if result:
    #                 bigger_matches.add( result )
    #         else:

    #             job = q.enqueue(jobs.check_match, mpmath.mp.dps, repr(lhs_val), repr(rhs_val))
    #             work.add(job)

    #         if not silent:
    #             count += 1
    #             utils.printProgressBar(count, len(matches), prefix=f' Queueing {mpmath.mp.dps} places', suffix='     ')


    #     # Wait for the set of jobs
    #     results = jobs.wait(work, silent)

    #     for result in results:
    #         if result is not None:
    #             bigger_matches.add( (result[0], result[1]) )
            
    #     if not silent:
    #         print()
    #         print(f'Found {len(bigger_matches)} matches at {mpmath.mp.dps} decimal places ...')
        
    #     matches = bigger_matches

    # print(f'Saving matches.p  ... ')
    # pickle.dump( matches, open( "matches.p", "wb" ) )
    # dump_output("matches.p")

def generate_sequences(a_gen, b_gen):
    
    name, args = a_gen
    args = eval(args)
    a_seq = generate_sequence(name, *args)

    name, args = b_gen
    args = eval(args)
    b_seq = generate_sequence(name, *args)

    sequence_pairs = list(itertools.product(a_seq, b_seq))
    return sequence_pairs


def generate_sequence(name, *args):
    func = getattr(algorithms, name)
    seq = func(*args)

    return seq


def save():

    db = HashtableWrapper('match')

    i = 0
    filename = f'search-{i}.result.txt' 
    while os.path.exists(filename):
        i += 1
        filename = f'search-{i}.result.txt' 

    output = open(filename, 'w')


    postprocs = utils.get_funcs(postproc)
    algos = utils.get_funcs(algorithms)

    rhs_cache = set()

    index = 0
    total = len(list(db.scan())[0])

    # By the time we reach here, if there were any high-precision matches, 
    # dump out the data to the screen
    mpmath.mp.dps = 15 # back to default
    for match_keys in db.scan():
        for match_key in match_keys:
            
            lhs,rhs = eval(db.redis.get(match_key))

            # algo.type_id, fn.type_id, result, repr(args), a_gen, b_gen

            _, lhs_algo_id, lhs_post, lhs_result, lhs_args, lhs_seq_idx, lhs_a_gen, lhs_b_gen = eval(lhs)
            _, rhs_algo_id, rhs_post, rhs_result, rhs_args, rhs_seq_idx, rhs_a_gen, rhs_b_gen = eval(rhs)

            # print('')
            # print('-' * 60)
            # print('')

            lhs_output = ''
            rhs_output = ''

            #
            # output the fancy version for known functions
            #
            if lhs_algo_id == 0: # rational_function
                lhs_args = lhs_args # these are the arguments to the rational_function

                numerator = lhs_args[0][0]
                denominator = lhs_args[1][0]

                # sequence generator function name and args
                func_name, func_args = lhs_a_gen
                poly_range, poly_x_values = eval(func_args)

                const = poly_x_values


                post = postprocs[lhs_post].__name__ + f'( {const} ) == '
                if lhs_post == 0: #identity
                    post = ''

                if lhs_result in utils.const_map:
                    lhs_result = f'{utils.const_map[lhs_result]} = {lhs_result}'
                
                if denominator != 1:
                    lhs_output = f'LHS: {post} {lhs_result}  ==>  {numerator} / {denominator}'
                else:
                    lhs_output = f'LHS: {post} {lhs_result}'
            else:
                lhs_output = f'LHS: const:{const} {postprocs[lhs_post].__name__}( {algos[lhs_algo_id].__name__} (a:{lhs_a_gen} b:{lhs_b_gen}))'

            # sequence_pairs = generate_sequences(rhs_a_gen, rhs_b_gen)
            # a, b = sequence_pairs[rhs_seq_idx]
            a, b = rhs_args

            if rhs_algo_id == 1: # continued fraction
                cont_frac = utils.cont_frac_to_string(a, b)
                post = postprocs[rhs_post].__name__ + '(x) <== '
                if rhs_post == 0: #identity
                    post = ''

                rhs_output = f'RHS: {rhs_result} == {post} {cont_frac}'
            elif rhs_algo_id == 2: # nested radical
                nest_rad = utils.nested_radical_to_string(a, b)
                post = postprocs[rhs_post].__name__ + '(x) <== '
                if rhs_post == 0: #identity
                    post = ''
                
                rhs_output = f'RHS: {rhs_result} == {post} {nest_rad}'

            else:
                rhs_output = f'RHS: {rhs_result} {postprocs[rhs_post].__name__}( {algos[rhs_algo_id].__name__} (a:{rhs_a_gen} b:{rhs_b_gen})) for x => poly range:{poly_range}'
            
            if rhs_output in rhs_cache:
                # print('DUPLICATE:')
                continue

            # print(lhs_output)
            output.write(lhs_output)
            output.write('\n')
            # print(rhs_output)
            output.write(rhs_output)
            # output.write('\n')

            rhs_cache.add(rhs_output)
            # print()
            output.write('\n\n')

            index += 1
            utils.printProgressBar(index, total, prefix=f'Writing output {index} / {total}')
        
        print()
        print(f'Found {total} matches at {mpmath.mp.dps} decimal places')
        print()
        output.close()




