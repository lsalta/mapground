# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import absolute_import

from MapGround import MapGroundException, LayerNotFound, LayerAlreadyExists, LayerImportError
from django.utils import timezone
from datetime import datetime
from fileupload.models import Archivo
from .models import TablaGeografica, ArchivoRaster
from MapGround.settings import IMPORT_SCHEMA, ENCODINGS, UPLOADED_RASTERS_PATH
from sequences import get_next_value
from utils.db import drop_table, setup_inheritance, add_column, have_same_structure
from utils.commons import normalizar_texto
from .utils import get_shapefile_files, load_shape, DEFAULT_SRID, get_epsg_from_prj, get_raster_metadata, determinar_id_capa
from layers.models import Capa, TipoDeGeometria, RasterDataSource, VectorDataSource, CONST_VECTOR, CONST_RASTER
from django.contrib.gis.geos import Point, Polygon, MultiPolygon
import os
import shutil
import pytz

def __borrarArchivoRasterConMismoDatetime(capa, dt):
    q=capa.rasterdatasources.filter(data_datetime=dt)
    if q.count() > 0:
        rds=q.first()
        print 'Ya existe un archivo con el mismo datetime: %s. Borrandolo...'%(rds.location)
        arch=ArchivoRaster.objects.get(path_del_archivo=rds.location)
        arch.delete()
        rds.delete()

def import_shapefile(filename, schema, table, encoding='LATIN1', create_table_only=False):
    try:
        st = get_shapefile_files(filename)
    except MapGroundException:
        raise

    srid = DEFAULT_SRID
    try:
        srid = get_epsg_from_prj(st['prj'])
    except KeyError:
        pass

    try:
        load_shape(st['shp'], schema, table, srid, encoding, create_table_only)
    except MapGroundException:
        raise
    print 'import srid %d' % srid

    return srid

def _get_raster_date_time(raster_metadata):
    # Mapserver no soporta datetimes con microsegundos en WMS-T
    data_datetime = timezone.now().replace(microsecond=0).replace(tzinfo=pytz.utc)
    if raster_metadata['raster_count'] > 0:
        try:
            # Toda esta logica es MUY ad-hoc
            # Cuanto de esto funcionara en general para otros gribs y/o rasters es dudosisimo
            grib_ref_time = raster_metadata['metadata_json']['gdalinfo']['bands'][0]['metadata']['']['GRIB_VALID_TIME']
            data_datetime = datetime.utcfromtimestamp(int(grib_ref_time.split(' ')[0], 10)).replace(tzinfo=pytz.utc)
        except Exception as e:
            print unicode(e)
    return data_datetime

def import_vector_layer(request, id_capa, next_version, archivo, filename, encoding):
    try:
        nombre_de_tabla = id_capa + '_v' + str(next_version)
        # Acá se crea un tabla padre vacía con el id_capa para después heredar
        import_shapefile(unicode(archivo.file), IMPORT_SCHEMA, id_capa, encoding, create_table_only=True)
        srid = import_shapefile(unicode(archivo.file), IMPORT_SCHEMA, nombre_de_tabla, encoding)
        setup_inheritance(IMPORT_SCHEMA, id_capa, nombre_de_tabla)
        data_datetime = timezone.now().replace(second=0,microsecond=0).replace(tzinfo=pytz.utc)
        add_column(IMPORT_SCHEMA, id_capa, "data_datetime", "timestamp with time zone", data_datetime)

        tabla_geografica = TablaGeografica.objects.create(
            nombre_normalizado=normalizar_texto(archivo.nombre),
            nombre_del_archivo=os.path.basename(unicode(archivo.file)),
            esquema=IMPORT_SCHEMA,
            srid=srid,
            tabla=nombre_de_tabla,
            owner=request.user)

        c = Capa.objects.create(
            owner=tabla_geografica.owner,
            nombre=tabla_geografica.nombre_normalizado,
            id_capa=id_capa,    # equivalente a tabla_geografica.tabla,
            tipo_de_capa=CONST_VECTOR,
            nombre_del_archivo=None,
            conexion_postgres=None,
            esquema=tabla_geografica.esquema,
            tabla=tabla_geografica.tabla,
            gdal_metadata=dict(),
            gdal_driver_shortname='Shapefile',
            gdal_driver_longname='ESRI Shapefile',
            tipo_de_geometria=TipoDeGeometria.objects.all()[0],  # uno cualquiera, pues el capa_pre_save lo calcula y lo overridea
            proyeccion_proj4='',    # TODO:!
            srid=tabla_geografica.srid)

        VectorDataSource.objects.create(
            owner=request.user,
            capa=c,
            proyeccion_proj4=c.proyeccion_proj4,
            srid=srid,
            extent=MultiPolygon(Polygon.from_bbox(
                (c.extent_minx_miny.x,c.extent_minx_miny.y,
                c.extent_maxx_maxy.x,c.extent_maxx_maxy.y))),
            conexion_postgres=None,
            esquema=tabla_geografica.esquema,
            tabla=tabla_geografica.tabla,
            campo_geom='geom',
            data_datetime=data_datetime,
            cantidad_de_registros=c.cantidad_de_registros
        )

        for a in Archivo.objects.filter(owner=request.user, nombre=os.path.splitext(filename)[0]):
            a.delete()

    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar importar la capa vectorial "{0}": {1}'.format(filename, unicode(e))))

    return c

def import_raster_layer(request, id_capa, next_version, archivo, filename):
    # Validamos primero la consistencia entre el 'filename' y un raster valido, por ejemplo, para evitar vulnerabilidad por url
    raster = get_raster_metadata(archivo.file.name)
    if raster is None:
        raise LayerImportError('Se produjo un error al intentar importar la capa "{0}" CODE: R1'.format(filename))

    extent_capa = raster['extent_capa']
    extent_capa_4326 = raster['extent_capa_4326']
    proyeccion_proj4 = raster['proyeccion_proj4']

    # srid = raster['srid'] if raster['srid'] is not None else 0
    srid = raster['srid']           # casos GeoTiff o cualquier otro raster con dato SRID valido
    if srid is None:
        if proyeccion_proj4 != '':
            srid = 0                # casos GRIB, no hay SRID pero hay proj4
        else:
            srid = 4326             # casos netCDF, no hay nada, pero son 4326, y algo tenemos que asumir

    # El 'import' del raster consiste en moverlo al path destino...
    # directorio_destino = UPLOADED_RASTERS_PATH + unicode(request.user) + '/'
    # filename_destino = directorio_destino + id_capa + archivo.extension
    # El 'import' del raster consiste en moverlo al path destino...
    directorio_destino = UPLOADED_RASTERS_PATH + unicode(request.user) + '/'
    nombre_del_archivo = id_capa + '_v' + str(next_version) + archivo.extension
    filename_destino = directorio_destino + nombre_del_archivo 
    data_datetime = _get_raster_date_time(raster)
    try:
        if not os.path.exists(directorio_destino):
            os.makedirs(directorio_destino)
        shutil.move(archivo.file.name, filename_destino)
    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar copiar el archivo raster {0}: {1}  CODE: R2'.format(filename, unicode(e))))

    # ...y luego creamos los objetos
    try:
        
        archivo_raster = ArchivoRaster.objects.create(
            owner=request.user,
            nombre_del_archivo=nombre_del_archivo,
            path_del_archivo=filename_destino,
            formato_driver_shortname=raster['driver_short_name'],
            formato_driver_longname=raster['driver_long_name'],
            srid=srid)                

        c = Capa.objects.create(
            owner=request.user,
            nombre=normalizar_texto(archivo.nombre),
            id_capa=id_capa,
            tipo_de_capa=CONST_RASTER,
            nombre_del_archivo=archivo_raster.nombre_del_archivo,
            cantidad_de_bandas=raster['raster_count'],
            size_height=raster['size_height'],
            size_width=raster['size_width'],
            conexion_postgres=None,
            gdal_metadata=raster['metadata_json'],
            gdal_driver_shortname=raster['driver_short_name'],
            gdal_driver_longname=raster['driver_long_name'],
            tipo_de_geometria=TipoDeGeometria.objects.get(nombre='Raster'),
            proyeccion_proj4=proyeccion_proj4,
            srid=srid,
            extent_minx_miny=Point(float(extent_capa_4326[0]), float(extent_capa_4326[1]), srid=4326),
            extent_maxx_maxy=Point(float(extent_capa_4326[2]), float(extent_capa_4326[3]), srid=4326),
            layer_srs_extent=' '.join(map(str, extent_capa)),
            cantidad_de_registros=None)

        RasterDataSource.objects.create(
            owner=request.user,
            capa=c,
            nombre_del_archivo=nombre_del_archivo,
            location=c.dame_data(None),
            proyeccion_proj4=proyeccion_proj4,
            srid=srid,
            extent=MultiPolygon(Polygon.from_bbox(extent_capa)),
            gdal_driver_shortname=raster['driver_short_name'],
            gdal_driver_longname=raster['driver_long_name'],
            gdal_metadata=raster['metadata_json'],
            cantidad_de_bandas=raster['raster_count'],
            size_height=raster['size_height'],
            size_width=raster['size_width'],   
            data_datetime=data_datetime             
        )

        archivo.delete()

    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar importar la capa raster {0}: {1}  CODE: R3'.format(filename, unicode(unicode(e)))))
    
    return c

def update_vector_layer(request, capa, next_version, archivo, filename, encoding):
    id_capa=capa.id_capa
    try:
        nombre_de_tabla = id_capa + '_v' + str(next_version)
        srid = import_shapefile(unicode(archivo.file), IMPORT_SCHEMA, nombre_de_tabla, encoding)
        data_datetime = timezone.now().replace(second=0,microsecond=0).replace(tzinfo=pytz.utc)
        add_column(IMPORT_SCHEMA, nombre_de_tabla, "data_datetime", "timestamp with time zone", data_datetime)
        if not have_same_structure(id_capa, nombre_de_tabla):
            drop_table(IMPORT_SCHEMA, nombre_de_tabla)
            raise ValueError('La tabla no tiene la misma estructura que la original.')
        else:
            setup_inheritance(IMPORT_SCHEMA, id_capa, nombre_de_tabla)

        tabla_geografica = TablaGeografica.objects.create(
            nombre_normalizado=normalizar_texto(archivo.nombre),
            nombre_del_archivo=os.path.basename(unicode(archivo.file)),
            esquema=IMPORT_SCHEMA,
            srid=srid,
            tabla=nombre_de_tabla,
            owner=request.user)

        capa.tabla=nombre_de_tabla
        capa.save()

        VectorDataSource.objects.create(
            owner=request.user,
            capa=capa,
            proyeccion_proj4=capa.proyeccion_proj4,
            srid=srid,
            extent=MultiPolygon(Polygon.from_bbox(
                (capa.extent_minx_miny.x,capa.extent_minx_miny.y,
                capa.extent_maxx_maxy.x,capa.extent_maxx_maxy.y))),
            conexion_postgres=None,
            esquema=tabla_geografica.esquema,
            tabla=tabla_geografica.tabla,
            campo_geom='geom',
            data_datetime=data_datetime,
            cantidad_de_registros=capa.cantidad_de_registros
        )

        for a in Archivo.objects.filter(owner=request.user, nombre=os.path.splitext(filename)[0]):
            a.delete()
        
    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar importar la capa vectorial "{0}": {1}'.format(filename, unicode(e))))

def update_raster_layer(request, capa, next_version, archivo, filename):
    id_capa=capa.id_capa
    # Validamos primero la consistencia entre el 'filename' y un raster valido, por ejemplo, para evitar vulnerabilidad por url
    # print 'Archivo raster para actualizar: %s'%(archivo.file.name)
    raster = get_raster_metadata(archivo.file.name)
    if raster is None:
        raise LayerImportError('Se produjo un error al intentar importar la capa "{0}" CODE: R1'.format(filename))

    extent_capa = raster['extent_capa']
    extent_capa_4326 = raster['extent_capa_4326']
    proyeccion_proj4 = raster['proyeccion_proj4']

    # srid = raster['srid'] if raster['srid'] is not None else 0
    srid = raster['srid']           # casos GeoTiff o cualquier otro raster con dato SRID valido
    if srid is None:
        if proyeccion_proj4 != '':
            srid = 0                # casos GRIB, no hay SRID pero hay proj4
        else:
            srid = 4326             # casos netCDF, no hay nada, pero son 4326, y algo tenemos que asumir

    # El 'import' del raster consiste en moverlo al path destino...
    directorio_destino = UPLOADED_RASTERS_PATH + unicode(request.user) + '/'
    nombre_del_archivo = id_capa + '_v' + str(next_version) + archivo.extension
    filename_destino = directorio_destino + nombre_del_archivo 
    data_datetime = _get_raster_date_time(raster)
    try:
        if not os.path.exists(directorio_destino):
            os.makedirs(directorio_destino)
        shutil.move(archivo.file.name, filename_destino)
    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar copiar el archivo raster {0}: {1}  CODE: R2'.format(filename, unicode(e))))

    # ...y luego creamos los objetos
    try:

        # Esto sirve para permitir actualizar los datos de una capa para una fecha dada
        # en forma automatica (sin tener que borrar a mano la versión anterior)
        # Tipicamente seria cuando detectas un error en los datos, lo corregis y volves a 
        # subir o bien para el caso de SMN cuando actualizan el pronostico.
        __borrarArchivoRasterConMismoDatetime(capa, data_datetime)

        # print MultiPolygon(Polygon.from_bbox(extent_capa))
        # return render(request, template_name, {
        #     "capa": filename, "ok": False,
        #     "error_msg": 'El update es la version %d, destino %s'%(next_version, filename_destino)})
        archivo_raster = ArchivoRaster.objects.create(
            owner=request.user,
            nombre_del_archivo=nombre_del_archivo,
            path_del_archivo=filename_destino,
            formato_driver_shortname=raster['driver_short_name'],
            formato_driver_longname=raster['driver_long_name'],
            srid=srid)

        # print 'Datetime: %s'%str(data_datetime)
        RasterDataSource.objects.create(
            owner=request.user,
            capa=capa,
            nombre_del_archivo=nombre_del_archivo,
            location=filename_destino,
            proyeccion_proj4=proyeccion_proj4,
            srid=srid,
            extent=MultiPolygon(Polygon.from_bbox(extent_capa)),
            gdal_driver_shortname=raster['driver_short_name'],
            gdal_driver_longname=raster['driver_long_name'],
            gdal_metadata=raster['metadata_json'],
            cantidad_de_bandas=raster['raster_count'],
            size_height=raster['size_height'],
            size_width=raster['size_width'],   
            data_datetime=data_datetime             
        )
        
        capa.nombre_del_archivo=archivo_raster.nombre_del_archivo
        capa.cantidad_de_bandas=raster['raster_count']
        capa.size_height=raster['size_height']
        capa.size_width=raster['size_width']
        capa.gdal_metadata=raster['metadata_json']
        capa.gdal_driver_shortname=raster['driver_short_name']
        capa.gdal_driver_longname=raster['driver_long_name']
        capa.tipo_de_geometria=TipoDeGeometria.objects.get(nombre='Raster')
        capa.proyeccion_proj4=proyeccion_proj4
        capa.srid=srid
        capa.extent_minx_miny=Point(float(extent_capa_4326[0]), float(extent_capa_4326[1]), srid=4326)
        capa.extent_maxx_maxy=Point(float(extent_capa_4326[2]), float(extent_capa_4326[3]), srid=4326)
        capa.layer_srs_extent=' '.join(map(str, extent_capa))
        capa.save()

        archivo.delete()

    except Exception as e:
        raise(LayerImportError('Se produjo un error al intentar importar la capa raster {0}: {1}  CODE: R3'.format(filename, unicode(unicode(e)))))

def import_layer(request, filename, encoding='LATIN1'):
    # Chequeo basico de consistencia entre el parametro 'filename' de la vista y algun Archivo existente
    try:
        archivo = Archivo.objects.get(owner=request.user, slug=filename)  # filename tiene la forma "nombre.extension"
    except (MapGroundException) as e:  # no deberia pasar...
        raise LayerNotFound('No se pudo encontrar la capa "{0}" para importar.'.format(filename))
    
    # determinamos el id unico que le corresponde a esta capa, sin importar si es vector o raster, y verificamos que no exista en la IDE
    id_capa = determinar_id_capa(request, archivo.nombre)
    next_version=get_next_value(id_capa)
    # print "Proxima version es %d"%(next_version)

    try:
        existe = Capa.objects.get(id_capa=id_capa)     # este chequeo podría ser reemplazado a futuro por la funcionalidad de "upload nueva versión de la capa"
        raise(LayerAlreadyExists('Ya existe una capa suya con el nombre "{0}" en la IDE.'.format(filename)))
    except:
        if archivo.extension == '.shp':     # Esto podría mejorarse guardando el tipo de archivo en el modelo Archivo
            return import_vector_layer(request, id_capa, next_version, archivo, filename, encoding)

        else:   # casos rasters
            return import_raster_layer(request, id_capa, next_version, archivo, filename)

def update_layer(request, capa, filename, encoding='LATIN1'):
    # Chequeo basico de consistencia entre el parametro 'filename' de la vista y algun Archivo existente
    try:
        archivo = Archivo.objects.get(owner=request.user, slug=filename)  # filename tiene la forma "nombre.extension"
    except (MapGroundException) as e:  # no deberia pasar...
        raise LayerNotFound('No se pudo encontrar la capa "{0}" para importar.'.format(filename))
    
    next_version=get_next_value(capa.id_capa)
    # print "Proxima version es %d"%(next_version)

    try:
        if archivo.extension == '.shp':     # Esto podría mejorarse guardando el tipo de archivo en el modelo Archivo
            update_vector_layer(request, capa, next_version, archivo, filename, encoding)
        else:
            update_raster_layer(request, capa, next_version, archivo, filename)

    except Exception as e:
        raise e

    return capa
