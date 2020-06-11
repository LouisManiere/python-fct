from setuptools import setup, find_packages
from distutils.extension import Extension
import numpy
from Cython.Build import cythonize


extensions = [

    Extension(
        'speedup',
        ['cython/speedup.pyx'],
        language='c++',
        include_dirs=[numpy.get_include()]
    ),

    Extension(
        'terrain_analysis',
        ['cython/terrain/terrain_analysis.pyx'],
        language='c++',
        include_dirs=[numpy.get_include()]
    )

]

setup(
    name='fct-cli',
    version='1.0.5',
    # packages=find_packages(),
    ext_modules=cythonize(extensions),
    include_package_data=True,
    install_requires=[
        'numpy>=1.18',
        'scipy>=1.4',
        'rasterio>=1.0.22',
        'fiona>=1.8.6',
        'Click>=7.0'
    ],
#     entry_points='''
# [console_scripts]
# autodoc=fct.cli.autodoc:autodoc
# fct=fct.cli.algorithms:fct
# fcw=fct.cli.algorithms:workflows
#     ''',
)
