from hdbcli import dbapi
import pandas as pd
import os
import csv
import re
from pandas import _config  # Importar el módulo CSV
import Logs  # type: ignore
from datetime import date, datetime, timedelta
from google.cloud import bigquery
from google.oauth2 import service_account
import shutil
import json

#--------------------------------------- Configuración de Fechas ------------------------------------##

hoy = datetime.today()

# Primer y último día del mes actual
primer_dia_mes_actual = hoy.replace(day=1).strftime("%Y-%m-%d")
if hoy.month == 12:
    proximo_mes = hoy.replace(year=hoy.year + 1, month=1, day=1)
else:
    proximo_mes = hoy.replace(month=hoy.month + 1, day=1)
ultimo_dia_mes_actual = (proximo_mes - timedelta(days=1)).strftime("%Y-%m-%d")

# Primer día del mes anterior
if hoy.month == 1:
    primer_dia_mes_anterior = hoy.replace(year=hoy.year - 1, month=12, day=1).strftime("%Y-%m-%d")
else:
    primer_dia_mes_anterior = hoy.replace(month=hoy.month - 1, day=1).strftime("%Y-%m-%d")

#--------------------------------------- Leer configuración desde archivo externo --------------------##
 
with open("config_parametros.json") as f:
    bq_config = json.load(f)

#--------------------------------------- Parametros de Conexion SAP HANA  ----------------------------##

HANA_HOST = bq_config["conexion_hana"]["host"]
HANA_PORT = bq_config["conexion_hana"]["port"]
HANA_USER = bq_config["conexion_hana"]["user"]
HANA_PASSWORD = bq_config["conexion_hana"]["password"]

#--------------------------------------- Conexión a SAP HANA -----------------------------------------##

try:
    conn = dbapi.connect(
        address=HANA_HOST,
        port=HANA_PORT,
        user=HANA_USER,
        password=HANA_PASSWORD
    )
    print("[1] [INICIO] Conexión a SAP HANA Establecido [OK]")
    Logs.mensaje("[1.1] [INICIO] Conexión a SAP HANA - Establecido [OK]")
except Exception as e:
    print("[1.1] [ERROR] Conexión a SAP HANA NO Establecido")
    Logs.mensaje("[1.2] [ERROR] Conexión a SAP HANA NO Establecido")

#--------------------------------------- Rutas & Vistas SAP HANA ------------------------------------##

# Rutas de salida para los archivos CSV por empresa
RUTA_BASE_GDM = bq_config["vistas_hana"]["6010"]["ruta"]
RUTA_BASE_IMF = bq_config["vistas_hana"]["3010"]["ruta"]
RUTA_BASE_PLACA = bq_config["vistas_hana"]["1100"]["ruta"]

# Vistas HANA a consultar y nombre del archivo CSV resultante
VISTAS_HANA_GDM = bq_config["vistas_hana"]["6010"]["vista"]
VISTAS_HANA_IMF = bq_config["vistas_hana"]["3010"]["vista"]
VISTAS_HANA_PLACA = bq_config["vistas_hana"]["1100"]["vista"]

# Prefijos identificadores por ruta (para historiales, por ejemplo)
prefijos_historico = {
    RUTA_BASE_GDM: "GDM",
    RUTA_BASE_IMF: "IMFRISA",
    RUTA_BASE_PLACA: "PLACA"
}

#--------------------------------------- Extracción de Vistas SAP HANA ------------------------------------##

# Función para extraer datos de una vista de HANA y guardarlos en un archivo CSV
def extraer_y_guardar_vista(vista, archivo_csv, base_path):
    try:
        print(f"[2] [INICIO] Extrayendo datos de la vista: {vista}")
        Logs.mensaje(f"[2] [INICIO] Extrayendo datos de la vista: {vista}")

        # Conectar a SAP HANA
        conn = dbapi.connect(
            address=HANA_HOST,
            port=HANA_PORT,
            user=HANA_USER,
            password=HANA_PASSWORD
        )
        cursor = conn.cursor()
        query = f"SELECT * FROM {vista}"
        cursor.execute(query)

        # Extraer datos y crear DataFrame
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(data, columns=columns)

        # Guardar datos en archivo CSV
        file_path = os.path.join(base_path, archivo_csv)
        df.to_csv(file_path, index=False, sep=';', encoding="utf-8", quoting=csv.QUOTE_MINIMAL)

        print(f"[2.1] [PROCESO] Archivo CSV guardado correctamente: {file_path}")
        Logs.mensaje(f"[2.1] [PROCESO] Archivo CSV guardado correctamente: {file_path}")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[2.2] [ERROR] Ocurrió un error al procesar la vista {vista}: {e}")
        Logs.mensaje(f"[2.2] [ERROR] Ocurrió un error al procesar la vista {vista}: {e}")

# Procesar vistas mover o copiar los archivos generados a una carpeta histórica
for base_path, vistas in [(RUTA_BASE_GDM, VISTAS_HANA_GDM), (RUTA_BASE_IMF, VISTAS_HANA_IMF), (RUTA_BASE_PLACA, VISTAS_HANA_PLACA)]:
    fecha_hoy = datetime.today().strftime('%Y-%m-%d')
    prefijo = prefijos_historico.get(base_path)
    historico_path = os.path.join(base_path.replace("sapb1", r"sapb1\HISTORICO"), f"{prefijo}-{fecha_hoy}")

    # Crear carpeta histórica si no existe
    if not os.path.exists(historico_path):
        os.makedirs(historico_path)
        print(f"[2.3] [PROCESO] Carpeta histórica creada: {historico_path}")
        Logs.mensaje(f"[2.3] [PROCESO] Carpeta histórica creada: {historico_path}")

    # Extraer y guardar cada vista
    for vista, archivo in vistas.items():
        extraer_y_guardar_vista(vista, archivo, base_path)
        shutil.copy(os.path.join(base_path, archivo), os.path.join(historico_path, archivo))
        print(f"[2.4] [PROCESO] Archivo movido a histórico: {historico_path}\\{archivo}")
        Logs.mensaje(f"[2.4] [PROCESO] Archivo movido a histórico: {historico_path}\\{archivo}")

print("[2.5] [ÉXITO] Extracción Guardado CSV Completado [OK]")
Logs.mensaje("[2.5] [ÉXITO] Extracción Guardado CSV Completado [OK]")

#--------------------------------------- Unificación de Archivos CSV Margen Bruto ------------------------------------##

# Función para unificar archivos CSV en uno solo
def unificar_archivos_csv():
    try:
        # Lista de archivos a unificar, con su ruta y origen
        archivos = [
            (os.path.join(bq_config["vistas_hana"]["6010"]["ruta"], bq_config["vistas_hana"]["6010"]["narchivo"]), "GDM"),
            (os.path.join(bq_config["vistas_hana"]["3010"]["ruta"], bq_config["vistas_hana"]["3010"]["narchivo"]), "IMF"),
            (os.path.join(bq_config["vistas_hana"]["1100"]["ruta"], bq_config["vistas_hana"]["1100"]["narchivo"]), "PLACA")
        ]

        print("[3] [INICIO] Proceso de unificación de archivos CSV...")
        Logs.mensaje("[3] [INICIO] Proceso de unificación de archivos CSV...")

        dataframes = []  # Lista para almacenar los DataFrames
        columnas = None   # Variable para almacenar las columnas del primer archivo

        # Leer cada archivo CSV y almacenarlo en una lista de DataFrames
        for i, (archivo, origen) in enumerate(archivos):
            if os.path.exists(archivo):  # Verificar si el archivo existe
                if i == 0:
                    df = pd.read_csv(archivo, sep=';', encoding="utf-8", engine='python')  # Leer el primer archivo
                    columnas = df.columns.tolist()  # Guardar las columnas
                else:
                    # Leer los siguientes archivos y mantener las mismas columnas
                    df = pd.read_csv(archivo, sep=';', encoding="utf-8", header=None, engine='python')
                    df.columns = columnas
                    if (df.iloc[0].astype(str).tolist() == columnas):  # Eliminar fila de encabezado si es repetida
                        df = df[1:]
              

                dataframes.append(df)  # Agregar DataFrame a la lista
            else:
                print(f"[3.1] [ADVERTENCIA] No se encontró el archivo: {archivo}.")
                Logs.mensaje(f"[3.1] [ADVERTENCIA] No se encontró el archivo: {archivo}.")

        # Si se encontraron archivos, concatenarlos y guardar el archivo consolidado
        if dataframes:
            df_consolidado = pd.concat(dataframes, ignore_index=True)
            ruta_salida = bq_config["ruta_salida_csv"]
            df_consolidado.to_csv(ruta_salida, index=False, sep=';', encoding="utf-8", quoting=csv.QUOTE_MINIMAL, escapechar=' ')
            print(f"[3.2] [PROCESO] Archivo CSV consolidado creado en: {ruta_salida}")
            Logs.mensaje(f"[3.2] [PROCESO] Archivo CSV consolidado creado en: {ruta_salida}")
        else:
            print("[3.3] [ADVERTENCIA] No se encontraron archivos para consolidar.")
            Logs.mensaje("[3.3] [ADVERTENCIA] No se encontraron archivos para consolidar.")
    except Exception as e:
        print(f"[3.4] [ERROR] Ocurrió un error al intentar unificar los archivos CSV: {e}")
        Logs.mensaje(f"[3.4] [ERROR] Ocurrió un error al intentar unificar los archivos CSV: {e}")

# Ejecutar la función
unificar_archivos_csv()

print("[3.5] [ÉXITO] Unificación CSV completado [OK]")
Logs.mensaje("[3.5] [ÉXITO] Unificación CSV completado [OK]")

#--------------------------- Inicializar Cliente de BigQuery y Configuración ------------------#

# Fechas para eliminación
fecha_inicio_mes_ant = primer_dia_mes_anterior
fecha_inicio_mes = primer_dia_mes_actual
fecha_fin_mes = ultimo_dia_mes_actual

# Ruta al archivo de credenciales
ruta_credenciales = os.path.join(os.getcwd(), "Sapb1datastudioPRD.json")
credentials = service_account.Credentials.from_service_account_file(ruta_credenciales)

# Cliente de BigQuery
project_id = bq_config["project"]
dataset_id = bq_config["dataset_id"]
table_id = bq_config["table_id"]
client = bigquery.Client(credentials=credentials, project=project_id)

# ----------------------------------  Validar existencia de tabla --------------------------- #

# Validar o crear la tabla en BigQuery

def validar_o_crear_tabla():
    schema = [
        bigquery.SchemaField(field["name"], field_type=field["type"])
        for field in bq_config["schema"]
    ]
    dataset_ref = client.dataset(dataset_id)
    table_ref = dataset_ref.table(table_id)

    print("[4] [INICIO] Creacion/Validacion de tabla si ya existe en BigQuery.")
    Logs.mensaje("[4] [INICIO] Creacion/Validacion de tabla si ya existe en BigQuery.")

    try:
        table = client.get_table(table_ref)
        print("[4.1] [INFO] La tabla ya existe en BigQuery.")
        Logs.mensaje("[4.1] [INFO] La tabla ya existe en BigQuery.")
    except Exception as e:
        print("[4.2] [INFO] La tabla no existe. Procediendo a crearla.")
        Logs.mensaje("[4.2] [INFO] La tabla no existe. Procediendo a crearla.")

        table = bigquery.Table(table_ref, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH,
            field=bq_config["partition_field"]
        )
        table.clustering_fields = bq_config["clustering_fields"]
    
        table = client.create_table(table)
        print(f"[4.2] [ÉXITO] Tabla creada exitosamente: {table.full_table_id} [OK].")
        Logs.mensaje(f"[4.2] [ÉXITO] Tabla creada exitosamente: {table.full_table_id} [OK].")

# Validar o crear la tabla en BigQuery
validar_o_crear_tabla()


#--------------------------- Eliminación de Meses en Curso en BigQuery --------------------------#

def eliminar_datos_mes_en_curso():
    query_delete = f"""
        DELETE FROM `{project_id}.{dataset_id}.{table_id}`
        WHERE {bq_config["partition_field"]} BETWEEN '{fecha_inicio_mes}' AND '{fecha_fin_mes}'
    """

    print(f"[5] [INICIO] Eliminando datos del mes en curso: {fecha_inicio_mes} a {fecha_fin_mes}.")
    Logs.mensaje(f"[5] [INICIO] Eliminando datos del mes en curso: {fecha_inicio_mes} a {fecha_fin_mes}.")

    query_job = client.query(query_delete)
    query_job.result()

    print("[5.1] [ÉXITO] Eliminación de datos del mes en curso completada [OK].")
    Logs.mensaje("[5.1] [ÉXITO] Eliminación de datos del mes en curso completada [OK].")


# Eliminar datos del mes actual en BigQuery
eliminar_datos_mes_en_curso()

#--------------------------- Carga CSV Unificado a BigQuery -----------------------------------#

def cargar_a_bigquery():
    try:
        ruta_csv_unificado = bq_config["ruta_salida_csv"]
       
        if not os.path.exists(ruta_csv_unificado):
            print(f"[6.0] [ADVERTENCIA] El archivo CSV no existe en la ruta: {ruta_csv_unificado}")
            Logs.mensaje(f"[6.0] [ADVERTENCIA] El archivo CSV no existe en la ruta: {ruta_csv_unificado}")
            return  # Salir de la función si no existe el archivo

        print("[6] [INICIO] Iniciando carga de datos CSV a BigQuery.")
        Logs.mensaje("[6] [INICIO] Iniciando carga de datos CSV a BigQuery.")

        schema = [bigquery.SchemaField(field["name"], field_type=field["type"]) for field in bq_config["schema"]]

        dataset_ref = client.dataset(dataset_id)
        table_ref = dataset_ref.table(table_id)

        # Configuración del Job
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            skip_leading_rows=1,
            source_format=bigquery.SourceFormat.CSV,
            field_delimiter=';',
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

        # Cargar datos
        with open(ruta_csv_unificado, "rb") as source_file:
            load_job = client.load_table_from_file(source_file, table_ref, job_config=job_config)
        load_job.result()

        print("[6.1] [ÉXITO] Carga de datos a BigQuery completada exitosamente [OK].")
        Logs.mensaje("[6.1] [ÉXITO] Carga de datos a BigQuery completada exitosamente [OK].")

    except Exception as e:
        print(f"[6.2] [ERROR] Ocurrió un error al cargar los datos a BigQuery: {e}")
        Logs.mensaje(f"[6.2] [ERROR] Ocurrió un error al cargar los datos a BigQuery: {e}")

# Ejecutar la carga
cargar_a_bigquery()


#--------------------------- Actualizacion de Procedimineto Almacenado en BigQuery -----------------------------------#

procedure_call1 = bq_config["procedure"]["stored1"]

try:
    query = f"CALL {procedure_call1}()"
    query_job = client.query(query)
    query_job.result()
    Logs.mensaje('[7] [ÉXITO] Procedimiento almacenado ejecutado [OK]')
    print('[7] [ÉXITO] Procedimiento almacenado ejecutado [OK]')
except Exception as e:
    Logs.mensaje(f'[7.1] [ERROR] Fallo al ejecutar procedimiento almacenado: {e}')
    print(f'[7.1] [ERROR] Fallo al ejecutar procedimiento almacenado: {e}')

 
print("[7.2] [FINALIZADO] Proceso de carga de datos finalizado [OK].")
Logs.mensaje("[7.2] [FINALIZADO] Proceso de carga de datos finalizado [OK].") 


print("______________________________________________________________")
Logs.mensaje("______________________________________________________________.")
