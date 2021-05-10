#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 13 11:53:22 2020

@author: kujawski
"""

import scipy.stats 
import numpy as np
import acoular
acoular.config.global_caching = "none"
from acoular import WNoiseGenerator, PointSource, SourceMixer, MicGeom
from acoupipe import NumericAttributeSampler, PointSourceSampler, \
    SourceSetSampler
from pylab import figure, plot, imshow, colorbar, show


rng1 = np.random.RandomState(1) # scipy listens to numpy random seed (when scipy seed is None)
rng2 = np.random.RandomState(2) # 

z = .5 # distance between array and source plane

# create random variable with rayleigh distribution to sample rms value
rayleigh_dist = scipy.stats.rayleigh(scale=5.)
# create normal distribution to sample source positions
normal_dist = scipy.stats.norm(loc=0,scale=0.1688)

mg = MicGeom( from_file="array64_d0o686.xml" )


# create white noise signals and pointsources
wn_list = []
ps_list = []
for i in range(10):
    wn_list.append(
        WNoiseGenerator(sample_freq=51200,seed=10+i, rms=1.0, numsamples=51200))
    ps_list.append(
        PointSource(signal=wn_list[i],mics=mg,loc=(0.,0.,z)))

sm = SourceMixer(sources=ps_list)
ps = acoular.PowerSpectra( time_data=sm, block_size=512, window='Hanning' )
rg = acoular.RectGrid( x_min=-0.5, x_max=0.5, y_min=-0.5, y_max=0.5, z=z, \
increment=0.01 )
st = acoular.SteeringVector( grid = rg, mics=mg, steer_type='true location' )
bb = acoular.BeamformerBase( freq_data=ps, steer=st)


# create sampler object to sample rms value with rayleigh distribution
rms_sampling = NumericAttributeSampler(random_var=rayleigh_dist, 
                                       target=wn_list, 
                                       attribute='rms',
                                       random_state=rng1)

#sample PointSource positions
ps_sampling = PointSourceSampler(random_var=normal_dist,
                                 target=ps_list,
                                 ldir=np.array([[1.0],[1.0],[0]]),
                                 x_bounds=(-.5,.5),
                                 y_bounds=(-.5,.5),
                                 random_state=rng2,
                                 )

# sample number of sources
src_sampling = SourceSetSampler(
                                  target=[sm],
                                  set=ps_list,
                                  random_state=rng3)

# sample five different source cases and plot beamforming result
cfreq = 2000
for i in range(5):
    # sample
    rms_sampling.sample()
    ps_sampling.sample()
    src_sampling.sample()
    # recalculate
    pm = bb.synthetic( cfreq, 1 )
    Lm = acoular.L_p( pm )
    # plot
    figure()
    imshow( Lm.T, origin = "lower", vmin=Lm.max()-15, extent=rg.extend(), \
    interpolation='bicubic')
    for src in sm.sources:
        (x,y,_) = src.loc
        plot(x,y,marker="x",color="red")
    colorbar()
    show()




