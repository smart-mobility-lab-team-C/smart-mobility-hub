"""Install the M2 bringup package and runtime entry points."""
from glob import glob

from setuptools import find_packages, setup

package_name = 'smart_hub_bringup'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    entry_points={'console_scripts': ['reset_coordinator = smart_hub_bringup.reset:main']},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='M2 launch and acknowledged reset orchestration.',
    license='LicenseRef-Proprietary',
)
