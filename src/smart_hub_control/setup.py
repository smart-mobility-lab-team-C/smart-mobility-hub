"""Install the smart_hub_control skeleton without runtime entry points."""
from setuptools import find_packages, setup

package_name = 'smart_hub_control'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='M1 package skeleton; no runtime nodes.',
    license='LicenseRef-Proprietary',
)
