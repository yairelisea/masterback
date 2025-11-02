


from datetime import datetime, timedelta
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import ActorReport, ReportType
import time

# ... (mantener imports existentes)

@router.get("/weekly-report")
async def get_weekly_report(
    q: str = Query(..., description="Nombre del actor político para el reporte semanal"),
    force_refresh: bool = Query(False, description="Forzar regeneración aunque exista cache"),
    db: AsyncSession = Depends(get_session)
):
    """
    Genera o recupera un reporte semanal de un actor político.
    
    Comportamiento:
    1. Busca si existe un reporte de las últimas 24 horas (cache)
    2. Si existe y force_refresh=False, devuelve del cache
    3. Si no existe o force_refresh=True, genera nuevo y guarda en BD
    4. Guarda TODO en el histórico (no se pierde nada)
    """
    try:
        # 1. Buscar reporte reciente en cache (< 24 horas)
        if not force_refresh:
            cache_query = select(ActorReport).where(
                ActorReport.actorName == q,
                ActorReport.reportType == ReportType.WEEKLY,
                ActorReport.createdAt > datetime.utcnow() - timedelta(hours=24)
            ).order_by(desc(ActorReport.createdAt))
            
            result = await db.execute(cache_query)
            cached_report = result.scalars().first()
            
            if cached_report:
                print(f"📦 Reporte semanal de '{q}' encontrado en cache")
                # Agrega metadata al response
                return {
                    **cached_report.reportData,
                    "_metadata": {
                        "from_cache": True,
                        "generated_at": cached_report.createdAt.isoformat(),
                        "report_id": cached_report.id
                    }
                }
        
        # 2. Generar nuevo reporte
        print(f"🔄 Generando nuevo reporte semanal para '{q}'")
        start_time = time.time()
        
        weekly_report_data = await perplexity_service.get_weekly_actor_report(
            actor_name=q
        )
        
        if weekly_report_data.get("error"):
            raise HTTPException(status_code=500, detail=weekly_report_data.get("error"))
        
        generation_time = time.time() - start_time
        
        # 3. Extraer resumen y contar items
        summary = weekly_report_data.get("resumen_ejecutivo", {}).get("sintesis", "")
        item_count = len(weekly_report_data.get("log_de_evidencia", []))
        
        # 4. Guardar en BD
        new_report = ActorReport(
            actorName=q,
            reportType=ReportType.WEEKLY,
            reportData=weekly_report_data,
            summary=summary[:500] if summary else None,  # Limitar a 500 chars
            generationTime=generation_time,
            itemCount=item_count
        )
        
        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)
        
        print(f"✅ Reporte semanal guardado en BD (ID: {new_report.id})")
        
        # 5. Devolver con metadata
        return {
            **weekly_report_data,
            "_metadata": {
                "from_cache": False,
                "generated_at": new_report.createdAt.isoformat(),
                "report_id": new_report.id,
                "generation_time": generation_time,
                "item_count": item_count
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al generar/guardar reporte semanal: {e}")
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte semanal: {e}")


@router.get("/daily-summary")
async def get_daily_summary(
    q: str = Query(..., description="Nombre del actor político para el resumen diario"),
    force_refresh: bool = Query(False, description="Forzar regeneración aunque exista cache"),
    db: AsyncSession = Depends(get_session)
):
    """
    Genera o recupera un resumen diario de un actor político.
    
    Comportamiento:
    1. Busca si existe un reporte de las últimas 6 horas (cache más corto)
    2. Si existe y force_refresh=False, devuelve del cache
    3. Si no existe o force_refresh=True, genera nuevo y guarda en BD
    4. Guarda TODO en el histórico (no se pierde nada)
    """
    try:
        # 1. Buscar reporte reciente en cache (< 6 horas)
        if not force_refresh:
            cache_query = select(ActorReport).where(
                ActorReport.actorName == q,
                ActorReport.reportType == ReportType.DAILY,
                ActorReport.createdAt > datetime.utcnow() - timedelta(hours=6)
            ).order_by(desc(ActorReport.createdAt))
            
            result = await db.execute(cache_query)
            cached_report = result.scalars().first()
            
            if cached_report:
                print(f"📦 Resumen diario de '{q}' encontrado en cache")
                return {
                    **cached_report.reportData,
                    "_metadata": {
                        "from_cache": True,
                        "generated_at": cached_report.createdAt.isoformat(),
                        "report_id": cached_report.id
                    }
                }
        
        # 2. Generar nuevo resumen
        print(f"🔄 Generando nuevo resumen diario para '{q}'")
        start_time = time.time()
        
        daily_summary_data = await perplexity_service.get_daily_actor_summary(
            actor_name=q
        )
        
        if daily_summary_data.get("error"):
            raise HTTPException(status_code=500, detail=daily_summary_data.get("error"))
        
        generation_time = time.time() - start_time
        
        # 3. Extraer resumen y contar items
        summary = daily_summary_data.get("resumen_diario_express", "")
        item_count = len(daily_summary_data.get("registro_de_evidencia", []))
        
        # 4. Guardar en BD
        new_report = ActorReport(
            actorName=q,
            reportType=ReportType.DAILY,
            reportData=daily_summary_data,
            summary=summary[:500] if summary else None,
            generationTime=generation_time,
            itemCount=item_count
        )
        
        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)
        
        print(f"✅ Resumen diario guardado en BD (ID: {new_report.id})")
        
        # 5. Devolver con metadata
        return {
            **daily_summary_data,
            "_metadata": {
                "from_cache": False,
                "generated_at": new_report.createdAt.isoformat(),
                "report_id": new_report.id,
                "generation_time": generation_time,
                "item_count": item_count
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al generar/guardar resumen diario: {e}")
        raise HTTPException(status_code=500, detail=f"Error al generar el resumen diario: {e}")


# NUEVO: Endpoint para ver histórico de reportes
@router.get("/reports/history")
async def get_reports_history(
    actor_name: str = Query(..., description="Nombre del actor"),
    report_type: Optional[str] = Query(None, description="Filtrar por tipo: 'weekly' o 'daily'"),
    limit: int = Query(50, ge=1, le=200, description="Número máximo de reportes"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    db: AsyncSession = Depends(get_session)
):
    """
    Obtiene el histórico de reportes de un actor.
    
    Útil para:
    - Ver evolución temporal
    - Comparar reportes pasados
    - Análisis de tendencias
    """
    try:
        query = select(ActorReport).where(
            ActorReport.actorName == actor_name
        )
        
        if report_type:
            query = query.where(ActorReport.reportType == ReportType(report_type))
        
        query = query.order_by(desc(ActorReport.createdAt)).limit(limit).offset(offset)
        
        result = await db.execute(query)
        reports = result.scalars().all()
        
        # Formato simplificado para listado
        return {
            "actor_name": actor_name,
            "total": len(reports),
            "reports": [
                {
                    "id": r.id,
                    "type": r.reportType.value,
                    "created_at": r.createdAt.isoformat(),
                    "summary": r.summary,
                    "item_count": r.itemCount,
                    "generation_time": r.generationTime
                }
                for r in reports
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener histórico: {e}")


# NUEVO: Endpoint para obtener un reporte específico por ID
@router.get("/reports/{report_id}")
async def get_report_by_id(
    report_id: str,
    db: AsyncSession = Depends(get_session)
):
    """
    Obtiene un reporte específico por su ID.
    Útil para ver reportes históricos completos.
    """
    try:
        result = await db.execute(
            select(ActorReport).where(ActorReport.id == report_id)
        )
        report = result.scalars().first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        
        return {
            **report.reportData,
            "_metadata": {
                "report_id": report.id,
                "actor_name": report.actorName,
                "report_type": report.reportType.value,
                "generated_at": report.createdAt.isoformat(),
                "generation_time": report.generationTime,
                "item_count": report.itemCount
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener reporte: {e}")




