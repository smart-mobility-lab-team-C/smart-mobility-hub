"""Install the image-derived passenger detector."""
from glob import glob

from setuptools import find_packages, setup

package_name = 'smart_hub_perception'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/models', glob('models/*')),
    ],
    entry_points={'console_scripts': [
        'passenger_detector = smart_hub_perception.detector:main',
    ]},
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Smart Mobility Hub team',
    maintainer_email='maintainers@example.invalid',
    description='Image-derived queue detection.',
    license='LicenseRef-Proprietary',
)
