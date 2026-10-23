"""Install the M2 control package and runtime entry points."""
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
    entry_points={'console_scripts': [
        'parking_manager = smart_hub_control.m4_nodes:parking_main',
        'traffic_monitor = smart_hub_control.m4_nodes:traffic_main',
        'crossing_arbiter = smart_hub_control.crossing:main',
        'route_planner = smart_hub_control.routing:main',
        'bus_manager = smart_hub_control.bus:main',
        'm3_synthetic_roads = smart_hub_control.fixtures:main',
    ]},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='Crossing ownership arbitration.',
    license='LicenseRef-Proprietary',
)
