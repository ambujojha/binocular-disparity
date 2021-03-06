"""
Run the full disparity algorithm (CNN + CRF) on all images from the middlebury
stereo dataset
"""
from __future__ import division, print_function
import argparse
import sys
import os
import shutil
import csv
import numpy as np
import tensorflow as tf
import keras.backend as K

from disparity import cnn, crf, util, data

parser = argparse.ArgumentParser()
parser.add_argument('--data_dir', default='../data/middlebury', type=str)
parser.add_argument('--results_dir', default='../results/cnn_crf', type=str)
parser.add_argument('--nb_samples', default=None, type=int)
parser.add_argument('--shift_mode', default='before', type=str)
parser.add_argument('--crf_alg', default='GD', type=str)
parser.add_argument('--gpu_id', default='0', type=str)
ARGS = parser.parse_args()



def write(results):
    fname = os.path.join(ARGS.results_dir, "results.csv")
    with open(fname, mode='a') as f:
        scores_writer = csv.writer(
            f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL
        )
        scores_writer.writerow(results)

def check_overwrite():
    val = input("Results directory '%s' already exists. Would you like to "
                "overwrite? [y/n]: " % ARGS.results_dir)
    if val in ['y', 'n']:
        return val
    else:
        print("Must enter 'y' or 'n'.")
        return check_overwrite()

def main():
    # check command line params
    assert ARGS.gpu_id in [str(i) for i in range(10)]
    if ARGS.shift_mode == 'before':
        print('Shifting before CNN transform')
    elif ARGS.shift_mode == 'after':
        print('Shifting after CNN transform')
    else:
        raise Exception("'shift_mode' must be either 'before' or 'after'")
    if ARGS.crf_alg == 'GD':
        print('Using gradient descent MAP inference for CRF')
    elif ARGS.crf_alg == 'LBP':
        print('Using loopy belief propagation MAP inference for CRF')
    else:
        raise Exception("'crf_alg' must be either 'GD' or 'LBP'")

    # initialize results directory
    if os.path.isdir(ARGS.results_dir):
        if check_overwrite() == 'n':
            sys.exit(0)
        shutil.rmtree(ARGS.results_dir)
    os.mkdir(ARGS.results_dir)

    # initialize TensorFlow session
    gpu_options = tf.GPUOptions(allow_growth=True,
                                visible_device_list=ARGS.gpu_id)
    sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))
    K.set_session(sess)

    # load the middlebury dataset
    print('Loading image data...')
    samples = data.load_middlebury_dataset(
        ARGS.data_dir, nb_samples=ARGS.nb_samples, max_size=400
    )

    # add header to results csv
    write(['thresh','spearman_CNN','spearman_CRF','pearson_CNN','pearson_CRF'])

    # loop through samples
    for i in range(len(samples)):
        print('Processing image #%i' % i)
        img_L, img_R, _, disp_R = samples[i]
        height, width, _ = img_L.shape

        print('Computing disparities...')
        # compute disparity energies
        energies = cnn.compute_energies(
            img_L, img_R, numDisparities=120, shift_mode=ARGS.shift_mode
        )
        # select disparity threshold
        print('Selecting disparity threshold...')
        thresh = util.select_disparity_threshold(energies)
        print('best threshold: %i' % thresh)
        energies = energies[:,:,:thresh]
        disparity_CNN = np.argmin(energies, axis=2)
        # compute scores
        spearman_CNN = util.score_disparity(disparity_CNN, disp_R, mode='spearman')
        pearson_CNN = util.score_disparity(disparity_CNN, disp_R, mode='pearson')
        print('rho_CNN: %0.3f' % spearman_CNN)

        # perform CRF smoothing
        if ARGS.crf_alg == 'GD':
            print('Performing gradient descent CRF smoothing...')
            smoother = crf.GradientDescent(height,width,thresh,session=sess)
            disparity_CRF = smoother.decode_MAP(energies,lr=0.01,iterations=100)
        elif ARGS.crf_alg == 'LBP':
            print('Performing loopy belief propagation CRF smoothing...')
            smoother = crf.LoopyBP(height,width,thresh)
            disparity_CRF = smoother.decode_MAP(energies,iterations=20)
        else:
            raise Exception
        # compute new scores
        spearman_CRF = util.score_disparity(disparity_CRF, disp_R, mode='spearman')
        pearson_CRF = util.score_disparity(disparity_CRF, disp_R, mode='pearson')
        print('rho_CRF: %0.3f' % spearman_CRF)

        # save results
        write([thresh,spearman_CNN,spearman_CRF,pearson_CNN,pearson_CRF])
        fname_CNN = os.path.join(ARGS.results_dir, 'disp%0.3i_CNN.npy'%i)
        fname_CRF = os.path.join(ARGS.results_dir, 'disp%0.3i_CRF.npy'%i)
        np.save(fname_CNN, disparity_CNN.astype(np.int16))
        np.save(fname_CRF, disparity_CRF.astype(np.int16))

if __name__ == '__main__':
    main()