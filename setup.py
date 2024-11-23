from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="dns-manager",
    version="0.1.0",
    author="abitwiseman",
    author_email="abitwiseman@gmail.com",
    description="DNS server management tool for CentOS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
    install_requires=[
        "paramiko>=2.7.0",
    ],
)