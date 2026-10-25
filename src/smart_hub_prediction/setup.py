"""Install the trained demand predictor and offline model."""
from glob import glob

from setuptools import find_packages, setup

package_name = 'smart_hub_prediction'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/models', glob('models/*.json')),
    ],
    entry_points={'console_scripts': [
        'demand_predictor = smart_hub_prediction.predictor:main',
    ]},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='Trained queue-demand forecasting.',
    license='LicenseRef-Proprietary',
)
