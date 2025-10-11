from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in maximus_tools/__init__.py
from maximus_tools import __version__ as version

setup(
	name="maximus_tools",
	version=version,
	description="Tooll for generating employee checkin, bank statatement formatting, and bill creation",
	author="Cloud Nine Technologies (CNT)",
	author_email="talal@aljishi.com",
	packages=find_packages(include=['maximus_tools', 'maximus_tools.*']),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
