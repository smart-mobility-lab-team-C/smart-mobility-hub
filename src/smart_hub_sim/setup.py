"""Install the M2 sim package and runtime entry points."""
from glob import glob

from setuptools import find_packages, setup

package_name = 'smart_hub_sim'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    entry_points={'console_scripts': ['scenario_runner = smart_hub_sim.scenario_runner:main']},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='Seeded simulator and independent actuator watchdogs.',
    license='LicenseRef-Proprietary',
)
