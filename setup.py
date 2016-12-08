import os
from setuptools import setup, find_packages
from aristotle_mdr import get_version

VERSION = get_version()

with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as readme:
    README = readme.read()

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='aristotle-metadata-registry',
    version=VERSION,
    packages=find_packages(),
    include_package_data=True,
    license='Aristotle-MDR Modified BSD Licence',
    description='Aristotle-MDR is an open-source metadata registry as laid out by the requirements of the IEC/ISO 11179:2013 specification.',
    long_description=README,
    url='https://github.com/aristotle-mdr/aristotle-metadata-registry',
    author='Samuel Spencer',
    author_email='sam@aristotlemetadata.com',
    classifiers=[
        'Development Status :: 3 - Alpha',

        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Healthcare Industry',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Science/Research',

        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    ],
    install_requires = [
        "Django>=1.8,<1.9",
        'pytz',
        'pyyaml',

        'django-model-utils==2.3.1',
        'django-notifications-hq>=1.0', #At least 0.8 for live notifications.
        'docutils',

        #Search requirements
        'django-haystack==2.4.1',
        'Whoosh',

        #Rich text editors
        'django-ckeditor>=5.0.0',

        # Revision control
        "django-reversion==1.10.1",
        'django-reversion-compare>=0.6.1,<0.7',
        'diff-match-patch',

        # Fancy UI stuff
        'django-static-precompiler',
        'autocomplete==0.0.104'
        'django-autocomplete-light==2.3.3',
        'django-bootstrap3',
        'django-bootstrap3-datetimepicker',

        # This was migrated out of django1.7, needed for django1.8
        'django-formtools',

        'html5lib==1.0b8',
        'xhtml2pdf',
        #'django-tastypie'

        # required for help, but thats required
        'django-autoslug',

    ],

)
