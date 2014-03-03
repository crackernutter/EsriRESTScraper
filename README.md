EsriRESTScraper
===============

A Python class that scrapes ESRI Rest Endpoints and exports data to a geodatabase

This class is instantiated with the Esri REST Endpoint of a feature layer inside a map service.  For secured map services, you can include an optional token when instantiating the class. 
<br> e.g. 
```python
import RestCacheClass
earthquakes = RestCacheClass.RestCache("http://rmgsc.cr.usgs.gov/ArcGIS/rest/services/nhss_haz/MapServer/3")
```


The RestCache object scrapes the feature layer page for it's various attributes: fields, wkid, max record count, name, and geometry type.

This class has two primary methods:

1. createFeatureClass
2. updateFeatureClass

createFeatureClass
==================

This attribute


