import arcpy, os, sys, urllib2, urllib, json, re, datetime, httplib, time
########Exceptions###############
class SchemaMismatch(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return self.value
class IncorrectWorkspaceType(SchemaMismatch):
    pass
class TooManyRecords(SchemaMismatch):
    pass
class MapServiceError(SchemaMismatch):
    pass
class NullGeometryError(SchemaMismatch):
    pass
  
########GENERAL FUNCTIONS#################
#Basic function to return an array with geometry from a multi-geometry object (polyline and polygon)
def getMultiGeometry(geometry):
    geom = arcpy.Array()
    for feature in geometry:
        array = arcpy.Array()
        for point in feature:
            point = arcpy.Point(point[0], point[1])
            array.add(point)
        geom.add(array)
    return geom

#Basic function to return Boolean of whether the uri is a file geodatabase or not
def validWorkspace(uri):
    if ".gdb" in str(uri) or ".sde" in str(uri):
        return True
    else:
        return False

#Basic function to return Geometry type for a given REST endpoint
#To do - add handing for Multipoint
def getGeometryType(restGeom):
    if "Polygon" in restGeom:
        return "POLYGON"
    elif "Polyline" in restGeom:
        return "POLYLINE"
    elif "Point" in restGeom:
        return "POINT"
    else:
        return "Unknown"

#basic function to return json from a specific query
def findIndex(data, string):
    for i,j in enumerate(data):
        if string in j:
            return i
    return -999


###############REST CACHE CLASS###########################
class RestCache:
    def __init__(self, url, token=None, userFields = []):
        self.url = url
        self.token = token
        self.userFields = userFields
        self.__setAttributes()

    def __str__(self):
        return "RestCache object based on %s" %self.url

    def _getEsriRESTJSON(self, url, params, attempt=1):
        if self.token != None:
            params['token'] = self.token
        if attempt <= 5:
            data = urllib.urlencode(params)
            req = urllib2.Request(url, data)
            try:
                response = urllib2.urlopen(req)
                headers = response.info().headers
            except httplib.BadStatusLine as e:
                return self._getEsriRESTJSON(url, params, attempt+1)
            except urllib2.HTTPError as e:
                print "sleeping"
                time.sleep(5)
                return self._getEsriRESTJSON(url, params, attempt+1)
            regex = '\d+'
            index = findIndex(headers,"Content-Length")
            if index != -999:
                responseLength = int(re.findall(regex, headers[index])[0])
                res=''
                while 1:
                    chunk = response.read(1000)
                    if chunk:
                        res += chunk
                    else:
                        break
                if len(res) == responseLength:
                    try:
                        final = json.loads(res)
                        return final
                    except ValueError as e:
                        return self._getEsriRESTJSON(url, params, attempt+1)
                else:
                    return self._getEsriRESTJSON(url, params, attempt+1)
            else:
                final = json.loads(response.read())
                if 'error' in final.keys():
                    return self._getEsriRESTJSON(url, params, attempt+1)
                else:
                    return final
        else:
            raise MapServiceError("Error Accessing Map Service " + self.url)

    #Function that sets the attributes of the RestCache object.  All attributes are retrieved from the URL endpoint
    #To do - M values and Z values
    def __setAttributes(self):
        values = {"f":"json"}
        layerInfo = self._getEsriRESTJSON(self.url,values)
        #Geometry Type
        geometryType = getGeometryType(layerInfo['geometryType'])
        self.geometryType = geometryType
        #Name
        name=arcpy.ValidateTableName(layerInfo['name'])
        self.name=name
        #Spatial Reference - both the wkid and the arcpy SpatialReference object
        #in case it's in a wkt
        try:
            wkid = layerInfo['extent']['spatialReference']['wkid']
        except:
            wkid = 4326
        sr = arcpy.SpatialReference()
        sr.factoryCode = int(wkid)
        sr.create()
        self.sr = sr
        self.wkid = wkid
        #field used to update the feature class are a subset of all the fields in a feature class
        fields = layerInfo['fields']
        updateFields = []
        for field in fields:
            if (field['type'] == 'esriFieldTypeOID' or field['type'] == 'esriFieldTypeGeometry' or 'shape' in field['name'].lower() or field['type'] == 'esriFieldTypeGUID' or field['name'] in self.userFields):
                pass
            else:
                updateFields.append(field)
        updateFields.insert(0, {"name":'Shape@', "type":"esriFieldTypeGeometry"})
        self.updateFields = updateFields
        #Max values
        if layerInfo.has_key('maxRecordCount'):
            self.maxRecordCount = int(layerInfo['maxRecordCount'])
        else:
            self.maxRecordCount = 1000

    #Primary public function creates the feature class and all necessary fields
    def createFeatureClass(self, location, name=""):
        if not validWorkspace(location):
            raise IncorrectWorkspaceType("Incorrect workspace - feature class must be created in a local geodatabase")
        if name!="":
            self.name = name
        self.featureClassLocation = location
        featureSet = arcpy.CreateFeatureclass_management(out_path=self.featureClassLocation, out_name=self.name, geometry_type=self.geometryType,spatial_reference=self.sr)
        self.__createFields()
        return featureSet

    #Function to create necessary fields from an Esri feature class
    def __createFields(self):
        fields = self.updateFields
        for field in fields:
                self.__createField(field)

    #Function to create an individual field for a feature class
    #To do - add field types for BLOB and other more rare field types
    def __createField(self, field):
        name = field['name']
        fType = field['type']
        fieldLength=None
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
        validatedName =  arcpy.ValidateFieldName(name, self.featureClassLocation)
        arcpy.AddField_management(in_table=featureClass,field_name=name,field_type=fieldType, field_length=fieldLength)

    #Primary public function to update a feature class based on a specific query
    #Function accepts string or list as query, and will iterate over list of queries for better performance
    def updateFeatureClass(self, featureClass, query=["1=1"], append=False, userFields=[]):
        #check if user fileds already exist
        if not self.userFields:
            self.userFields = userFields
        #check for errors
        if not validWorkspace(featureClass):
            raise IncorrectWorkspaceType("Incorrect workspace - feature class must be created in a local geodatabase")
        if not self.__matchSchema(featureClass):
            raise SchemaMismatch("Schema of input feature class does not match object schema")
        #make correct query
        if query == None:
            queries = ["1=1"]
        elif type(query) is not list:
            queries = [query]
        else:
            queries = query
        #Append or overwrite mode
        if not append:
                arcpy.DeleteFeatures_management(featureClass)

        #instantiate cursor
        updateFields = [f['name'] for f in self.updateFields]
        cursor = arcpy.da.InsertCursor(featureClass, updateFields)

        #iterate over queries
        for query in queries:
            if not self.__numRecordsLessThanMax(query):
                del cursor
                raise TooManyRecords("Query returns more than max allowed. Please refine query: " + query)
            rValues = {"where":query,
               "f":"json",
               "returnCountOnly":"false",
                "outFields": "*"}
            featureData = self._getEsriRESTJSON(self.url+"/query",rValues)
            for feature in featureData['features']:
                #if geometry is bad, skip record
                try:
                    geom = self.__getGeometry(feature['geometry'])
                except NullGeometryError as e:
                    print e
                    continue
                except:
                    print "Some other geometry error"
                attributes = []
                attributes.append(geom)
                for field in self.updateFields:
                    if 'shape' not in field['name'].lower():
                        if 'date' in field['type'].lower():
                            try:
                                if len(str(feature['attributes'][field['name']])) == 13:
                                    attributes.append(datetime.datetime.fromtimestamp(feature['attributes'][field['name']] / 1000))
                                else:
                                    attributes.append(datetime.datetime.fromtimestamp(feature['attributes'][field['name']]))
                            except ValueError:
                                attributes.append(None)
                            except TypeError:
                                attributes.append(None)
                        else:
                            #getting strange OverflowError Python int too large to convert to C long, so casting section
                            #getting problem with some services where some fields aren't returned in results so added try/catch block
                            try:
                                newAttribute = feature['attributes'][field['name']]
                                if type(newAttribute) is long:
                                    if type(int(newAttribute)) is long:
                                        attributes.append(float(newAttribute))
                                    else:
                                        attributes.append(newAttribute)
                                else:
                                    attributes.append(newAttribute)
                            except KeyError, e:
                                attributes.append(None)
                cursor.insertRow(attributes)
        #Delete cursor
        del cursor

    #Function to match the schema of a featureClass to the RestCache object to permit updating to continue
    def __matchSchema(self, featureClass):
        fClassFields = []
        for field in arcpy.ListFields(featureClass):
            if (field.name.lower() == 'objectid' or field.name.lower() == 'oid' or 'shape' in field.name.lower() or field.name in self.userFields):
                pass
            else:
                fClassFields.append(field.name)
        fClassFields.insert(0, 'Shape@')
        objFields = [f['name'] for f in self.updateFields]
        return sorted(fClassFields) == sorted(objFields)


    #Simple function to check that the number of records is less than the maximum possible to prevent an incomplete cache
    #To do - figure out what to do when the function returns false
    def __numRecordsLessThanMax(self, query="1=1"):
        numRecords = self.getNumRecordsFromQuery(query)
        return numRecords < self.maxRecordCount

    def getNumRecordsFromQuery(self, query="1=1"):
        rValues = {"where":query,
           "f":"json",
           "returnCountOnly":"true"}
        count = self._getEsriRESTJSON(self.url + "/query",rValues)
        numRecords = count['count']
        return numRecords

    #Function to return the Arcpy geometry type to be inserted in the update list
    def __getGeometry(self, geom):
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
        elif "POINT" in self.geometryType:
            try:
                point = arcpy.Point(geom['x'], geom['y'])
            except:
                raise NullGeometryError("Point geometry is invalid or null")
            pointGeom = arcpy.Geometry("point",point,self.sr)
            return pointGeom
