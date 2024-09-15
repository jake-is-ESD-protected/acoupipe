from setuptools import setup
import os

setup(
    name='acoupipe',
    version='24.04',  # Date based release versioning
    description='Library for the generation of large-scale microphone array data for machine learning',
    long_description=open('README.rst').read(),
    license='BSD License',
    author=[{'name': 'Acoular Development Team', 'email': 'info@acoular.org'}],
    maintainer=[{'name': 'Adam Kujawski', 'email': 'adam.kujawski@tu-berlin.de'},
                 {'name': 'Art Pelling', 'email': 'a.pelling@tu-berlin.de'},
                 {'name': 'Simon Jekosch', 'email': 's.jekosch@tu-berlin.de'}],
    keywords=['acoustics', 'beamforming', 'deep learning', 'machine learning', 'microphone array', 'sound source localization', 'sound source characterization'],
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Physics',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3 :: Only'
    ],
    project_urls={
        'Documentation': 'https://adku1173.github.io/acoupipe/',
        'Repository': 'https://github.com/adku1173/acoupipe',
        'Source': 'https://github.com/adku1173/acoupipe',
        'Tracker': 'https://github.com/adku1173/acoupipe/issues'
    },
    packages=['acoupipe'],
    # install_requires=[
    #     'acoular>=24.03',
    #     'ray',
    #     'h5py',
    #     'tqdm',
    #     'parameterized',
    #     'pooch'
    # ]
)