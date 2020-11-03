import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='gocheche',
    version='0.0.1',
    author='Nicholas Kullman',
    author_email='nick.kullman+cheche@gmail.com',
    description='A simple coffee routing utility.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/nkullman/go-cheche',
    packages=setuptools.find_packages(),
    # install_requires=['xmltodict'],
    # package_data={
    #     "frvcpy.test": ["data/*"],
    # },
    license='Apache',
    classifiers=[
        "Programming Language :: Python :: 3",
            "License :: OSI Approved :: Apache Software License",
            "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
    entry_points={
        'console_scripts': [
            'gocheche=gocheche.router:main',
            # 'frvcpy-translate=frvcpy.translator:main',
            # 'frvcpy-test=frvcpy.test.test:runAll'
        ],
    }
)
