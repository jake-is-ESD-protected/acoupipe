import ray
import argparse
import logging
import acoular
import numpy as np
from os import path
from scipy.stats import poisson, norm 
from acoular import config, MicGeom, WNoiseGenerator, PointSource, SourceMixer,\
    PowerSpectra, MaskedTimeInOut
from acoupipe import MicGeomSampler, PointSourceSampler, SourceSetSampler, \
    NumericAttributeSampler, ContainerSampler, DistributedPipeline, BasePipeline,\
        WriteTFRecord, WriteH5Dataset, float_list_feature, int_list_feature,\
            int64_feature
from features import get_source_loc, get_source_p2, get_csm, get_csmtriu, get_sourcemap
from helper import set_pipeline_seeds, set_filename

parser = argparse.ArgumentParser()
parser.add_argument('--datasets', nargs="+", default=["training"], choices=["training", "validation"],
                    help="Whether to compute both data sets ('all') or only the 'training' / 'validation' data set. Default is 'all'")
parser.add_argument('--tsamples', type=int, default=500000,
                    help="Total number of  training samples to simulate")
parser.add_argument('--vsamples', type=int, default=10000,
                    help="Total number of  validation samples to simulate")
parser.add_argument('--tpath', type=str, default=".",
                    help="path of simulated training data. Default is current working directory")
parser.add_argument('--vpath', type=str, default=".",
                    help="path of simulated validation data. Default is current working directory")
parser.add_argument('--file_format', type=str, default="tfrecord", choices=["tfrecord", "h5"],
                    help="Desired file format to store the data sets.")
parser.add_argument('--cache_dir', type=str, default=".",
                    help="path of cached data. Default is current working directory")
parser.add_argument('--he', type=float, default=None,
                    help="Returns only the features and targets for the specified helmholtz number, default is -1 (all frequencies will be considered)")
parser.add_argument('--nsources', type=int, default=None,
                    help="Calculates the data set with a fixed number of sources. Default is 'None', meaning that the number of sources present will be sampled randomly.")
parser.add_argument('--features', nargs="+", default=["csm"], choices=["sourcemap", "csmtriu", "csm"],
                    help="Whether to compute data set containing the csm or the beamforming map as the main feature. Default is 'csm'")
parser.add_argument('--tasks', type=int, default=1,
                    help="Number of asynchronous tasks. Defaults to '1' (non-distributed)")
parser.add_argument('--head', type=str, default=None,
                    help="IP address of the head node in the ray cluster. Only necessary when running in distributed mode.") 
parser.add_argument('--cache_csm', action="store_true",
                    help="Whether to cache the results of the CSM calculation") 
parser.add_argument('--log', action="store_true",
                    help="Whether to log timing statistics to file. Only for internal use.")                          
args = parser.parse_args()

# logging for debugging and timing statistic purpose
if args.log:
    logging.basicConfig(level=logging.INFO) # root logger
    logger = logging.getLogger()

# Fixed Parameters
VERSION="ds1-v001" # data set 1 , version 1.0
C = 343. # speed of sound
HE = 40 # Helmholtz number (defines the sampling frequency) 
SFREQ = HE*C # /ap with ap=1.0
BLOCKSIZE = 128 # block size used for FFT
SIGLENGTH=5 # length of the simulated signal
MFILE = "tub_vogel64_ap1.xml" # Microphone Geometry
REF_MIC = 63 # index of the reference microphone 

# Random Variables
mic_rvar = norm(loc=0, scale=0.001) # microphone array position noise; std -> 0.001 = 0.1% of the aperture size
pos_rvar = norm(loc=0,scale=0.1688) # source positions
nsrc_rvar = poisson(mu=3,loc=1) # number of sources

# Acoular Config
config.h5library = 'pytables' # set acoular cache file backend to pytables
config.cache_dir = path.join(args.cache_dir,'cache') # set up cache file dir
print("cache file directory at: ",config.cache_dir)

# Ray Config
if args.tasks > 1:
    ray.init(address=args.head)

# Computational Pipeline Acoular
# Microphone Geometry
mg_manipulated = MicGeom(from_file=MFILE) 
mg_fixed = MicGeom(from_file=MFILE)
# Signals
white_noise_signals = [
    WNoiseGenerator(sample_freq=SFREQ,seed=i+1,numsamples=SIGLENGTH*SFREQ) for i in range(16)
    ] 
# Monopole sources emitting the white noise signals
point_sources = [
    PointSource(signal=signal,mics=mg_manipulated) for signal in white_noise_signals
    ]
# Source Mixer mixing the signals of all sources (number will be sampled)
sources_mix = SourceMixer(sources=point_sources)

# Set up PowerSpectra objects to calculate CSM feature and reference p2 value
# first object is used to calculate the full CSM 
# second object will be used to calculate the p2 value at the reference microphone (for each present source)
ps_args = {'block_size':BLOCKSIZE, 'overlap':'50%', 'window':"Hanning", 'precision':'complex64'}
ps_csm = PowerSpectra(time_data=sources_mix,cached=args.cache_csm,**ps_args)
ps_ref = PowerSpectra(**ps_args,cached=False) # caching takes more time than calculation for a single channel
ps_ref.time_data = MaskedTimeInOut(source=sources_mix,invalid_channels=[_ for _ in range(64) if not _  == REF_MIC]) # masking other channels than the reference channel

# Set up Beamformer object to calculate sourcemap feature
if "sourcemap" in args.features:
    rg = acoular.RectGrid(
                    x_min=-0.5, x_max=0.5, y_min=-0.5, y_max=0.5, z=.5,increment=0.02)           
    st = acoular.SteeringVector(
                    grid=rg, mics=mg_fixed, steer_type='true level', ref=mg_fixed.mpos[:,REF_MIC])
    bb = acoular.BeamformerBase(
                    freq_data=ps_csm, steer=st, cached=False, r_diag=True, precision='float32')



# Computational Pipeline AcouPipe 

# callable function to draw and assign sound pressure RMS values to the sources of the SourceMixer object
def sample_rms(rng):
    "draw source pressures square, Rayleigh distribution, sort them, calc rms"
    nsrc = len(sources_mix.sources)
    p_rms = np.sqrt(np.sort(rng.rayleigh(5,nsrc))[::-1]) # draw source pressures square, Rayleigh distribution, sort them, calc rms
    p_rms /= p_rms.max() #norm it
    for i, rms in enumerate(p_rms):
        sources_mix.sources[i].signal.rms = rms # set rms value

mic_sampling = MicGeomSampler(
                    random_var=mic_rvar,
                    target=mg_manipulated,
                    ddir=np.array([[1.0],[1.0],[0]])
                    ) # ddir along two dimensions -> bivariate sampling

pos_sampling = PointSourceSampler(
                    random_var=pos_rvar,
                    target=sources_mix.sources,
                    ldir=np.array([[1.0],[1.0],[0.0]]), # ldir: 1.0 along first two dimensions -> bivariate sampling
                    x_bounds=(-.5,.5), # only allow values between -.5 and .5
                    y_bounds=(-.5,.5),
                    )

src_sampling = SourceSetSampler(    
                    target=[sources_mix],
                    set=point_sources,
                    replace=False,
                    numsamples=3,
                    ) # draw point sources from point_sources set (number of sources is sampled by nrcs_sampling object)
if args.nsources: src_sampling.numsamples = args.nsources

rms_sampling = ContainerSampler(
                    random_func=sample_rms)

nsrc_sampling =  NumericAttributeSampler(
                    random_var=nsrc_rvar, 
                    target=[src_sampling], 
                    attribute='numsamples',
                    )

if not args.nsources: # if no number of sources is specified, the number of sources will be samples randomly
    sampler_list = [mic_sampling, nsrc_sampling, src_sampling, rms_sampling, pos_sampling]
else:
    sampler_list = [mic_sampling, src_sampling, rms_sampling, pos_sampling]
 
if args.tasks > 1:
    pipeline = DistributedPipeline(
                    sampler=sampler_list,
                    numworkers=args.tasks,
                    )    
else:
    pipeline = BasePipeline(
                    sampler=sampler_list,
                    )


# Set up features to be stored in the data set
# desired (max.) number of sources
if args.nsources: 
    ns = args.nsources
else:
    ns = 16 
# determine desired frequency / frequency index (fidx) 
if args.he:
    freq = args.he*C # with apertur = 1.0
    # if data shall be calculated only for a certain frequency
    freq_data = list(ps_csm.fftfreq())
    if not freq in freq_data:
        fidx = ps_csm.fftfreq().searchsorted(freq)
        freq = ps_csm.fftfreq()[fidx]
    else:
        fidx = freq_data.index(freq)
        ps_csm.ind_low = fidx
        ps_csm.ind_high = fidx+1
else:
    fidx = None
    freq = None

# set up feature dict
feature_dict = {
    "loc": (get_source_loc, sources_mix, ns), # (callable, arg1, arg2, ...)
    "nsources": (lambda smix: len(smix.sources), sources_mix),
    "p2": (get_source_p2, sources_mix, ps_ref, fidx, ns, config.cache_dir),
}
# set up encoder functions to write to .tfrecord
encoder_dict = {
                "loc": float_list_feature,
                "p2": float_list_feature,
                "nsources": int64_feature,
                "idx": int64_feature,
                "seeds": int_list_feature,
                }

if "csm" in args.features:
    feature_dict.update(
        csm=(get_csm, ps_csm, fidx, config.cache_dir),
    )
    encoder_dict.update(
        csm=float_list_feature
    )

if "csmtriu" in args.features:
    feature_dict.update(
        csmtriu=(get_csmtriu, ps_csm, fidx, config.cache_dir),
    )
    encoder_dict.update(
        csmtriu=float_list_feature
    )

if "sourcemap" in args.features:
    feature_dict.update(
        sourcemap=(get_sourcemap, bb, freq, 0, config.cache_dir),
    )    
    encoder_dict.update(
        sourcemap=float_list_feature
    )

# add features to the pipeline
pipeline.features = feature_dict

# Create writer object to write data set to file
if args.file_format == "tfrecord":
    # create TFRecordWriter to save pipeline output to TFRecord File
    writer = WriteTFRecord(source=pipeline,
                            encoder_funcs=encoder_dict)
elif args.file_format == "h5":
    writer = WriteH5Dataset(source=pipeline,)

# compute the data sets
for dataset in args.datasets:
    print(dataset)
    if dataset == "training":
        samples = args.tsamples
        path = args.tpath
    elif dataset == "validation":
        samples = args.vsamples
        path = args.vpath
    set_pipeline_seeds(pipeline, samples, dataset)
    set_filename(writer,path,*[dataset,samples]+args.features+[f"{ns}src",f"he{args.he}",VERSION])
    
    # for debugging and timing statistics
    if args.log:
        pipeline_log = logging.FileHandler(".".join(writer.name.split('.')[:-1]) + ".log",mode="w") # log everything to file
        pipeline_log.setFormatter(logging.Formatter('%(process)d-%(levelname)s-%(asctime)s.%(msecs)02d-%(message)s', datefmt='%Y-%m-%d,%H:%M:%S'))
        logger.addHandler(pipeline_log) # attach handler to the root logger

    # start calculation
    writer.save() # start the calculation

    # remove handler
    if args.log:
        logger.removeHandler(pipeline_log)

