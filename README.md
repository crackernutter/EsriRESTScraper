EsriRESTScraper
===============

Have you ever come across a ArcGIS REST endpoint, and wished you could download the data locally?  Do you need to periodically update a local geodatabase with data from an ArcGIS Rest endpoint (instead of just using the external REST endpoint in a mapping application)?  Maybe you are not an authoritative data owner, and have some unique geoprocessing or workflow needs that cannot be completed using web services.   Or because you have 'disconnected environment' needs and would like to display the most recent copy of the data available before an internet outage.  Then use this!! I use it for downloading local copies of many of the USGS Natural Hazard Support System feeds to support local workflows (and more reliable web applications).   

A Python class that scrapes ESRI Rest Endpoints and parses the data into a local geodatabase

This class is instantiated with the Esri REST Endpoint of a feature layer inside a map service.  For secured map services, you can include an optional token when instantiating the class. 
<br> e.g. 
```python
import RestCacheClass
earthquakesScraper = RestCacheClass.RestCache("http://rmgsc.cr.usgs.gov/ArcGIS/rest/services/nhss_haz/MapServer/3")
```


The RestCache object when instantiated scrapes the feature layer page for it's various attributes: fields, wkid, max record count, name, and geometry type.

This class has two primary methods:

1. createFeatureClass
2. updateFeatureClass

createFeatureClass
==================

This method creates a feature class in a geodabase with the appropriate spatial reference, geometry type, and the appropriate fields (and field lengths, etc).  This method really only needs to be run a single time, then you have the correct feature class locally, and all you need to do is update it.

The name of the feature class is derived from the name in the REST endpoint, although this can be overwritten with an optional parameter.  

### Issues:

1.  The method only supports creating a feature class in a geodatabase, not a shapefile or SDE supported geodatabase.  If someone wants to modify this to support creating other types of workspaces, please do so!!
2.  Multipoint geometry is not supported.  Only polygon, polyline, and point geometries are supported.  
3.  Some field types are not supported either, although the most common ones are: text, date, short, long, double, float.

```python
earthquakesData = earthquakesScraper.createFeatureClass(r'C:\Geodata\earthquakes.gdb', 'earthquakes')
```

updateFeatureClass
==================

This method makes one or more REST calls, parses the data, and updates your local geodatabase.  Pretty straightforward.  This method accepts as input the feature class to update, a single query or list of queries (the default is "1=1"), and a Boolean value on whether to append to the existing dataset or overwrite (default is to overwrite since I didn't want to deal with differentials).

The method will gracefully end if there is a schema mismatch between the REST endpoint and the feature class to update, or if one of the queries returns a number of records equal to or more than the max records attribute specified in the REST endpoing.  

### Issues:

1. The method cannot handle how to deal with a query that returns more records and the max allowed by the service (default for most Esri REST endpoints is 1000.  Because using this data would result in an incomplete dataset, I just have the method throw an error.  A way around this is to just specific a series of queries in the query parameter, so long as each query won't exceed the max records, and the queries won't result in duplicate records.  However, a great goal would be to add some recursive function that creates a finer and finer geographic mesh, and break up the queries geographically until no query returns more records then the max.  This would be difficult for me, but is a great task for someone with the time and energy to devote to it.    

```python
earthquakesScraper.updateFeatureClass(earthquakesData, ["magnitude > 4"])
```

This is my first github contribution, and I hope someone can find it useful.  It does rely on Esri's software and the arcpy Python library, but there are no other external dependencies.  

Please let me know if you have any questions!



