This directory contains fixtures for system details, standard metadata and testing

* ``system.json`` - Django data needed for managaing aristotle, including the "system user" who sends messages from the registry
* ``iso_metadata.json`` - Implementations of iso standards useful for managing a registry
* ``test_metadata`` - Sample metadata useful for testing during development


Create user
-----------
sudo ./manage.py createsuperuser

Clear all data in tables
------------------------
sudo ./manage.py flush

Load Test Data Example
----------------------
sudo ./manage.py loaddata aristotle_mdr/fixtures/test_objectclass.json
sudo ./manage.py loaddata aristotle_mdr/fixtures/test_property.json
sudo ./manage.py loaddata aristotle_mdr/fixtures/test_dataelementconcept.json


* dont forget to reset the nextvalue id in the database for concept

Dump Data
---------
 ./manage.py dumpdata aristotle_mdr._concept --natural --indent=4 
 
Update Index
-------------
 sudo ./manage.py update_index