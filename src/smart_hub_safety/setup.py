"""Install the M2 safety package and runtime entry points."""
from setuptools import find_packages, setup

package_name = 'smart_hub_safety'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    entry_points={'console_scripts': ['safety_supervisor = smart_hub_safety.supervisor:main']},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='Independent command arbitration and protective stop recovery.',
    license='LicenseRef-Proprietary',
)
