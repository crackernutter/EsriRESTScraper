import os
import sys
import requests
import re
import datetime
import time
import logging
import arcpy

logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("matplotlib").setLevel(logging.ERROR)
########Exceptions################
class SchemaMismatch(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

class IncorrectWorkspaceType(SchemaMismatch):
    pass

class TooManyRecords(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

class MapServiceError(SchemaMismatch):
    pass

class NullGeometryError(SchemaMismatch):
    pass
########GENERAL FUNCTIONS#################

def getMultiGeometry(geometry):
    """Function to return an array with geometry from a multi-geometry object (polyline and polygon)
    Returns a geometry object: polygon with multiple rings or polyline with multiple paths"""
    geom = arcpy.Array()
    for feature in geometry:
        array = arcpy.Array()
        for point in feature:
            point = arcpy.Point(float(point[0]), float(point[1]))
            array.add(point)
        geom.add(array)
    return geom

def validWorkspace(uri):
    """Function to check whether workspace is a geodatbase"""
    if ".gdb" in str(uri) or ".sde" in str(uri):
        return True
    else:
        return False

def getGeometryType(restGeom):
    """Return geometry type from REST endpoint geometry value"""
    if "Polygon" in restGeom:
        return "POLYGON"
    elif "Polyline" in restGeom:
        return "POLYLINE"
    elif "Multipoint" in restGeom:
        return "MULTIPOINT"
    elif "Point" in restGeom:
        return "POINT"
    else:
        return "Unknown"

###############REST CACHE CLASS###########################

class RestCache:
    def __init__(self, url, token=None, userFields=[], excludeFields=[]):
        self.url = url
        self.token = token
        self.userFields = userFields
        self.excludeFields = excludeFields
        self.debugMode = False
        self.__setAttributes()

    def __str__(self):
        return "RestCache object based on %s" % self.url

    def __getEsriRESTJSON(self, url, params, attempt=1):
        """Helper function to query an Esri REST endpoint and return json"""
        # Wait five seconds if previous error
        if attempt > 1 and attempt != 6:
            time.sleep(5)
        # Set token if registered with object
        if self.token != None:
            params['token'] = self.token
        # all other attempts...
        if attempt <= 5:
            try:
                req = requests.get(url, params=params)
                response = req.json()
            except requests.exceptions.RequestException as e:
                self.__logMsg(40, "Exception {} {}".format(attempt, e))
                return self.__getEsriRESTJSON(url, params, attempt + 1)
            except ValueError as e:
                self.__logMsg(40, "Exception {} {}".format(attempt, e))
                return self.__getEsriRESTJSON(url, params, attempt + 1)
            if 'error' in response.keys():
                self.__logMsg(40, "Error in request: {}".format(response.message))
                return self.__getEsriRESTJSON(url, params, attempt + 1)
            elif 'features' in response.keys():
                return response['features']
            else:
                return response
        else:
            self.__logMsg(30, "Too many attempts")
            raise MapServiceError("Error Accessing Map Service " + self.url)

    # Function that sets the attributes of the RestCache object.  All attributes are retrieved from the URL endpoint
    # To do - M values and Z values

    def __setUpdateFields(self, serviceFields):
        """Sets the fields that will be updated from the FeatureService.  This does not include ID or Geometry fields"""
        updateFields = []
        ignoreFields = ['esriFieldTypeOID', 'esriFieldTypeGeometry', 'esriFieldTypeGUID', 'esriFieldTypeGlobalID']
        for field in serviceFields:
            if (field['type'] in ignoreFields or 'shape' in field['name'].lower() or field['name'] in self.userFields + self.excludeFields):
                pass
            else:
                updateFields.append(field)
        updateFields.insert(
            0, {"name": 'Shape@', "type": "esriFieldTypeGeometry"})
        self.updateFields = updateFields
        
    def __setAttributes(self):
        """Set attributes of object based on Esri REST Endpoint for FeatureService"""
        values = {"f": "json"}
        layerInfo = self.__getEsriRESTJSON(self.url, values)
        # Geometry Type
        geometryType = getGeometryType(layerInfo['geometryType'])
        self.geometryType = geometryType
        # Name
        name = arcpy.ValidateTableName(layerInfo['name'])
        self.name = name
        # Spatial Reference - both the wkid and the arcpy SpatialReference object
        # in case it's in a wkt
        try:
            wkid = layerInfo['extent']['spatialReference']['wkid']
        except:
            wkid = 4326
        sr = arcpy.SpatialReference()
        sr.factoryCode = int(wkid)
        sr.create()
        self.sr = sr
        self.wkid = wkid
        # field used to update the feature class are a subset of all the fields in a feature class
        fields = layerInfo['fields']
        self.__setUpdateFields(fields)
        # Max values
        if 'maxRecordCount' in layerInfo:
            self.maxRecordCount = int(layerInfo['maxRecordCount'])
        else:
            self.maxRecordCount = 1000

        #does pagination work?
        if 'advancedQueryCapabilities' in layerInfo:
            self.supportsPagination = layerInfo['advancedQueryCapabilities']['supportsPagination']
        else:
            self.supportsPagination = False

    def createFeatureClass(self, location, name="", excludeFields=[]):
        """Primary method to create a feature class based on an Esri
        FeatureService REST endpoint"""
        if not self.excludeFields:
            self.excludeFields = excludeFields
            self.updateFields = [
                f for f in self.updateFields if f['name'] not in self.excludeFields]
        if not validWorkspace(location):
            raise IncorrectWorkspaceType(
                "Incorrect workspace - feature class must be created in a local geodatabase")
        if name != "":
            self.name = name
        self.featureClassLocation = location
        featureset = arcpy.CreateFeatureclass_management(out_path=self.featureClassLocation,
                                                         out_name=self.name,
                                                         geometry_type=self.geometryType,
                                                         spatial_reference=self.sr)
        self.__createFields()
        return featureset

    def recreateFeatureClass(self, target, userFields=[], excludeFields=[]):
        """Method to recreate target feature class by recreating fields from REST Endpoint
        Can be invoked if SchemaMismatch error is thrown and caught"""

        self.featureClassLocation, self.name = os.path.split(target)
        existingFields = [f.name for f in arcpy.ListFields(target)]
        fieldsToRemove = [x for x in existingFields if x not in userFields and "shape" not in x.lower(
        ) and "objectid" not in x.lower() and "oid" not in x.lower()]
        arcpy.DeleteField_management(target, fieldsToRemove)
        self.__createFields()
        return target

    def __createFields(self):
        """Helper function to create fields when running createFeatureClass method"""
        for field in self.updateFields:
            self.__createField(field)

    def __createField(self, field):
        """Helper function to create individual field when running createFeatureClass method"""
        name = field['name']
        fType = field['type']
        fieldLength = None
        if 'shape' in name.lower():
            return
        elif "String" in fType:
            fieldType = "TEXT"
            fieldLength = field['length']
        elif "Date" in fType:
            fieldType = "DATE"
        elif "SmallInteger" in fType:
            fieldType = "SHORT"
        elif "Integer" in fType:
            fieldType = "LONG"
        elif "Double" in fType:
            fieldType = "DOUBLE"
        elif "Single" in fType:
            fieldType = "FLOAT"
        else:
            fieldType = "Unknown"
        featureClass = self.featureClassLocation + "\\" + self.name
        validatedName = arcpy.ValidateFieldName(
            name, self.featureClassLocation)
        arcpy.AddField_management(
            in_table=featureClass, field_name=name, field_type=fieldType, field_length=fieldLength)

    def __configDebug(self, debug, debugLoc):
        """Allows user to write some progess indicators to a log file"""
        if debug:
            self.debugMode = True
            module = os.path.basename(sys.argv[0])
            if module == '':
                module = 'restcache{}.log'.format(str(datetime.datetime.now()))
            else:
                module = module.replace(".py", ".log")
            logging.basicConfig(filename=os.path.join(debugLoc, module), level=logging.DEBUG)
            logging.getLogger().addHandler(logging.StreamHandler())
            logging.log(10, "Starting script at %s" %datetime.datetime.now())
            
    def __logMsg(self, level, *messages):
        """Handles logging"""
        if self.debugMode:
            for message in messages:
                logging.log(level, message)

    def updateFeatureClass(self, featureClass, query=["1=1"], append=False, userFields=[], excludeFields=[], debug=False, debugLoc=sys.path[0]):
        """Primary method to update an existing feature class by scraping Esri's REST endpoints.
         Method iterates over queries so user can specify non-overlapping queries to break up
         ingestion.  Method checks that the schemas of the source and destination match,
         ignoring fields in userFields paramter"""
        #uncomment this out to run every script in debug mode
        self.__configDebug(debug, debugLoc)
        # check if user fileds already exist
        if not self.userFields:
            self.userFields = userFields
        if not self.excludeFields:
            self.excludeFields = excludeFields
        # check for errors
        if not validWorkspace(featureClass):
            raise IncorrectWorkspaceType(
                "Incorrect workspace - feature class must be created in a local geodatabase")
        if not self.__matchSchema(featureClass):
            raise SchemaMismatch("Schema of input feature class does not match object schema")
        queries = self.__generateQuery(query)
        cursor = None

        # iterate over queries
        for query in queries:
            self.__logMsg(20, "Working on %s" % query)
            recordsInQuery = self.__getNumRecordsFromQuery(query)

            # Append or overwrite mode - prevents deletion if service is unavailable
            if all([not append, not cursor]):
                self.__logMsg(20, "Deleting records")
                arcpy.DeleteFeatures_management(featureClass)

            if recordsInQuery == 0:
                self.__logMsg(30, 'Skipping query')
                continue
            elif self.__numRecordsMoreThanMax(recordsInQuery) and self.supportsPagination == False:
                del cursor
                raise TooManyRecords("Query returns more than max allowed. Please refine query: " + query)
            else:
                pageStart = 0
                features = []
                while True:
                    rValues = {"where": query,
                       "f": "json",
                       "returnCountOnly": "false",
                       "outFields": "*",
                        "resultOffset":pageStart,
                        "outSR":self.sr.factoryCode}
                    featureData = self.__getEsriRESTJSON(self.url + "/query", rValues)
                    if len(featureData) == 0:
                        self.__logMsg(20, "No more results")
                        break
                    else:
                        self.__logMsg(20, "Successfully returned data")
                        features.extend(featureData)
                        pageStart += self.maxRecordCount
                        
            self.__logMsg(20, "Records Retrieved:", len(features))

            # instantiate cursor - if there is already a cursor, do nothing
            if not cursor:
                self.__logMsg(20, "Instantiating cursor")
                updateFields = [f['name'] for f in self.updateFields]
                cursor = arcpy.da.InsertCursor(featureClass, updateFields)
            for feature in features:
                # if geometry is bad, skip record
                try:
                    geom = self.__getGeometry(feature['geometry'])
                except NullGeometryError as e:
                    self.__logMsg(30, "Null geometry error")
                    continue
                except:
                    self.__logMsg(30, "Some other geometry error - couldn't get geometry")
                    continue
                attributes = []
                attributes.append(geom)
                for field in self.updateFields:
                    if field['name'] == "Shape@":
                        continue
                    else:
                        attributes.append(self.__getFieldFromFeature(feature, field))
                cursor.insertRow(attributes)

            self.__logMsg(20, "Finished writing data for query: %s" % query)
        # Delete cursor
        del cursor
    
    def __getFieldFromFeature(self, feature, field):
        attribute = feature['attributes'][field['name']]
        if 'date' in field['type'].lower():
            return self.__handleDateAttribute(attribute)
        else:
            """getting strange OverflowError Python int too large to convert to C long,
            so casting section getting problem with some services where some fields
            aren't returned in results so added try/catch block"""
            return attribute

    def __generateQuery(self, query):
        """Generates array of queries to send to endpoint from the function paramater"""
        if query == None:
            return ["1=1"]
        elif type(query) is not list:
            return [query]
        else:
            return query

    # Function to handle a date attribute (often passed as a UNIX timestamp)
    def __handleDateAttribute(self, timeString):
        """Based on length of Unix time string, returns the correct date"""
        try:
            if len(str(timeString)) >=11:
                return datetime.datetime.fromtimestamp(timeString / 1000)
            else:
                return datetime.datetime.fromtimestamp(timeString)
        except:
            return None

    def __matchSchema(self, featureClass):
        """Matches schema of featureClass to the RestCache object so updating can continue"""
        fClassFields = []
        for field in arcpy.ListFields(featureClass):
            fieldName = field.name.lower()
            if field.type == 'OID' or field.type == 'GlobalID' or 'shape' in fieldName or field.type == 'Geometry' or field.name in self.userFields:
                pass
            else:
                fClassFields.append(field.name)
        fClassFields.insert(0, 'Shape@')
        objFields = [f['name'] for f in self.updateFields]
        if sorted(fClassFields) == sorted(objFields):
            return True
        else:
            nonFields = [fname for fname in objFields if not fname in fClassFields]
            self.__logMsg(40, "Schema of input feature class does not match object schema", "Fields not in feature class but in feature service",str(nonFields))
            return False

    def __numRecordsMoreThanMax(self, numRecords):
        """Check record count is less than the maximum possible to prevent an incomplete cache"""
        return numRecords > self.maxRecordCount

    def __getNumRecordsFromQuery(self, query="1=1"):
        """Return number of records from REST endpoint based on query"""
        self.__logMsg(20,"Checking number of records in query")
        rValues = {"where": query, "f": "json", "returnCountOnly": "true"}
        count = self.__getEsriRESTJSON(self.url + "/query", rValues)
        numRecords = count['count']
        self.__logMsg(20,"Query contains %d records" % numRecords)
        return numRecords

    def __getGeometry(self, geom):
        """Function to return the Arcpy geometry type to be inserted in the update list"""
        if "POLYGON" in self.geometryType:
            rings = geom['rings']
            polygon = getMultiGeometry(rings)
            polyGeom = arcpy.Polygon(polygon, self.sr)
            return polyGeom
        elif "POLYLINE" in self.geometryType:
            paths = geom['paths']
            polyline = getMultiGeometry(paths)
            lineGeom = arcpy.Polyline(polyline, self.sr)
            return lineGeom
        elif "MULTIPOINT" in self.geometryType:
            points = geom['points']
            multigeom = arcpy.Multipoint(arcpy.Array([arcpy.Point(*coords) for coords in points]))
            return multigeom
        elif "POINT" in self.geometryType:
            try:
                point = arcpy.Point(float(geom['x']), float(geom['y']))
            except:
                raise NullGeometryError("Point geometry is invalid or null")
            pointGeom = arcpy.Geometry("point", point, self.sr)
            return pointGeom
