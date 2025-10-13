from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in cnt_tools/__init__.py
from cnt_tools import __version__ as version

setup(
	name="cnt_tools",
	version=version,
	description="CNT Tools - ERPNext tools by Cloud Nine Technologies",
	author="Cloud Nine Technologies (CNT)",
	author_email="info@cnt.bh",
	packages=find_packages(include=['cnt_tools', 'cnt_tools.*']),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
