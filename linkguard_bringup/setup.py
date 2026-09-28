from glob import glob
from setuptools import find_packages, setup

package_name = 'linkguard_bringup'

setup(
    name=package_name,
    version='0.3.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='student',
    maintainer_email='student@example.com',
    description='Nodes and launch files for LinkGuard.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'robot_sim = linkguard_bringup.robot_sim:main',
            'link_emulator = linkguard_bringup.link_emulator:main',
            'mission_server = linkguard_bringup.mission_server:main',
            'mission_client = linkguard_bringup.mission_client:main',
            'network_monitor = linkguard_bringup.network_monitor:main',
        ],
    },
)
