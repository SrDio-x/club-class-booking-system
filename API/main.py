from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from datetime import date, timedelta, datetime
from typing import Optional
import uvicorn

app = FastAPI()

# ─────────────────────────────────────
# CONFIG SUPABASE
# ─────────────────────────────────────

SUPABASE_URL = "https://odrnuepoyhewmwdhjzuj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9kcm51ZXBveWhld213ZGhqenVqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIwMjExMTQsImV4cCI6MjA4NzU5NzExNH0.jEbFDUXwVr71vfvotTShEhEkG74T65gDvw9e6Xsrir0"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

T_SOCIOS = "registros_socios_cc"
T_PROFESORES = "profesores_gimnasio"
T_RESERVAS = "reservas_clases_personalizadas"

# ─────────────────────────────────────
# MAPA DE DIAS
# ─────────────────────────────────────

DIAS = {
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sábado": 5,
    "sabado": 5,
    "domingo": 6
}

# ─────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────

def proxima_fecha(dia_semana: int) -> date:

    hoy = datetime.now().date()

    dias_adelante = (dia_semana - hoy.weekday() + 7) % 7

    if dias_adelante == 0:
        dias_adelante = 7

    return hoy + timedelta(days=dias_adelante)


def parsear_hora(hora_str: str) -> Optional[str]:

    formatos = ["%I%p", "%I:%M%p", "%H:%M"]

    hora_str = hora_str.replace(" ", "").lower()

    for fmt in formatos:
        try:
            dt = datetime.strptime(hora_str, fmt)
            return dt.strftime("%H:%M:00")
        except:
            pass

    return None


def validar_horario_gimnasio(hora_formateada: str):

    hora_int = int(hora_formateada.split(":")[0])

    if hora_int < 6 or hora_int > 21:
        raise HTTPException(
            status_code=400,
            detail="Horario fuera del horario del gimnasio (6am - 9pm)"
        )


# ─────────────────────────────────────
# MODELO REQUEST
# ─────────────────────────────────────

class ReservaRequest(BaseModel):

    id_accion: int
    cedula_profesor: int

    horario_texto: str

    dias: list[str]

    hora: str

    paquete: int

    pagador: str


# ─────────────────────────────────────
# CONSULTAR SOCIO
# ─────────────────────────────────────

@app.get("/consultar_socio/{id_accion}")
async def consultar_socio(id_accion: int):

    try:

        q = supabase.table(T_SOCIOS)\
            .select("*")\
            .eq("id_accion", id_accion)\
            .execute()

        if not q.data:
            raise HTTPException(
                status_code=404,
                detail="Socio no encontrado"
            )

        return q.data[0]

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ─────────────────────────────────────
# LISTAR PROFESORES
# ─────────────────────────────────────

@app.get("/profesores")
async def get_profesores():

    try:

        q = supabase.table(T_PROFESORES)\
            .select("*")\
            .execute()

        return q.data

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ─────────────────────────────────────
# HORARIOS OCUPADOS PROFESOR
# ─────────────────────────────────────

@app.get("/horarios_profesor/{cedula_profesor}")
async def horarios_profesor(cedula_profesor: int):

    try:

        q = supabase.table(T_RESERVAS)\
            .select("fecha_clase,hora_clase,horario_texto")\
            .eq("cedula_profesor", cedula_profesor)\
            .execute()

        return {
            "cedula_profesor": cedula_profesor,
            "reservas": q.data,
            "total_reservas": len(q.data)
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ─────────────────────────────────────
# CREAR RESERVA
# ─────────────────────────────────────

@app.post("/reservar")
async def reservar(reserva: ReservaRequest):

    try:

        # ───── validar socio

        socio_q = supabase.table(T_SOCIOS)\
            .select("*")\
            .eq("id_accion", reserva.id_accion)\
            .execute()

        if not socio_q.data:

            raise HTTPException(
                status_code=404,
                detail="Socio no encontrado"
            )

        socio = socio_q.data[0]

        if not socio.get("estado_socio", True):

            raise HTTPException(
                status_code=403,
                detail=f"El socio {socio['nombre']} está inactivo"
            )

        # ───── parsear hora

        hora_formateada = parsear_hora(reserva.hora)

        if not hora_formateada:

            raise HTTPException(
                status_code=400,
                detail=f"Hora inválida: {reserva.hora}"
            )

        validar_horario_gimnasio(hora_formateada)

        # ───── preparar reservas

        filas_a_insertar = []

        for dia in reserva.dias:

            dia_lower = dia.lower().strip()

            if dia_lower not in DIAS:

                raise HTTPException(
                    status_code=400,
                    detail=f"Día no reconocido: {dia}"
                )

            fecha = proxima_fecha(DIAS[dia_lower])

            fecha_str = fecha.isoformat()

            # conflicto profesor

            conflicto_prof = supabase.table(T_RESERVAS)\
                .select("id_reserva")\
                .eq("cedula_profesor", reserva.cedula_profesor)\
                .eq("fecha_clase", fecha_str)\
                .eq("hora_clase", hora_formateada)\
                .execute()

            if conflicto_prof.data:

                raise HTTPException(
                    status_code=409,
                    detail=f"Profesor ocupado {dia} {fecha_str} a las {reserva.hora}"
                )

            # conflicto socio

            conflicto_socio = supabase.table(T_RESERVAS)\
                .select("id_reserva")\
                .eq("id_socio", reserva.id_accion)\
                .eq("fecha_clase", fecha_str)\
                .eq("hora_clase", hora_formateada)\
                .execute()

            if conflicto_socio.data:

                raise HTTPException(
                    status_code=409,
                    detail=f"El socio ya tiene clase {dia} {fecha_str}"
                )

            filas_a_insertar.append({

                "id_socio": reserva.id_accion,

                "cedula_profesor": reserva.cedula_profesor,

                "fecha_clase": fecha_str,

                "hora_clase": hora_formateada,

                "horario_texto": reserva.horario_texto

            })

        # ───── insertar reservas

        try:

            respuesta = supabase.table(T_RESERVAS)\
                .insert(filas_a_insertar)\
                .execute()

        except Exception as e:

            if "duplicate key value violates unique constraint" in str(e):

                raise HTTPException(
                    status_code=409,
                    detail="Ese horario ya fue reservado"
                )

            raise HTTPException(
                status_code=500,
                detail=str(e)
            )

        # ───── respuesta para n8n

        return {

            "ok": True,

            "nombre_socio": socio["nombre"],

            "edad_socio": socio["edad"],

            "estado_socio": "Activo",

            "horario_texto": reserva.horario_texto,

            "dias_agendados": [f["fecha_clase"] for f in filas_a_insertar],

            "hora": hora_formateada,

            "paquete": reserva.paquete,

            "pagador": reserva.pagador,

            "reservas_creadas": len(filas_a_insertar),

            "ids_reserva": [r["id_reserva"] for r in respuesta.data]

        }

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ─────────────────────────────────────
# RUN
# ─────────────────────────────────────

if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )