"""Add actor_reports table

Revision ID: add_actor_reports
Revises: (poner aquí el ID de tu última migración)
Create Date: 2025-11-02 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_actor_reports'
down_revision = None  # CAMBIAR: Poner el ID de tu última migración
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear el ENUM para reportType
    report_type_enum = postgresql.ENUM('weekly', 'daily', name='reporttype', create_type=True)
    report_type_enum.create(op.get_bind(), checkfirst=True)
    
    # Crear tabla actor_reports
    op.create_table(
        'actor_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('actorName', sa.String(), nullable=False, comment='Nombre del actor político (ej: Samuel García)'),
        sa.Column('reportType', report_type_enum, nullable=False, comment="Tipo de reporte: 'weekly' o 'daily'"),
        sa.Column('reportData', postgresql.JSON(astext_type=sa.Text()), nullable=False, comment='Datos completos del reporte en formato JSON'),
        sa.Column('summary', sa.Text(), nullable=True, comment='Resumen rápido del reporte para búsquedas'),
        sa.Column('createdAt', sa.DateTime(), nullable=False, comment='Fecha de creación del reporte'),
        sa.Column('generationTime', sa.Float(), nullable=True, comment='Tiempo que tomó generar el reporte (segundos)'),
        sa.Column('itemCount', sa.Integer(), nullable=True, comment='Número de items/evidencias en el reporte'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Crear índices para mejorar performance
    op.create_index(op.f('ix_actor_reports_actorName'), 'actor_reports', ['actorName'], unique=False)
    op.create_index(op.f('ix_actor_reports_reportType'), 'actor_reports', ['reportType'], unique=False)
    op.create_index(op.f('ix_actor_reports_createdAt'), 'actor_reports', ['createdAt'], unique=False)
    
    # Índice compuesto para búsquedas comunes (actor + tipo + fecha)
    op.create_index(
        'ix_actor_reports_lookup',
        'actor_reports',
        ['actorName', 'reportType', 'createdAt'],
        unique=False
    )


def downgrade() -> None:
    # Eliminar índices
    op.drop_index('ix_actor_reports_lookup', table_name='actor_reports')
    op.drop_index(op.f('ix_actor_reports_createdAt'), table_name='actor_reports')
    op.drop_index(op.f('ix_actor_reports_reportType'), table_name='actor_reports')
    op.drop_index(op.f('ix_actor_reports_actorName'), table_name='actor_reports')
    
    # Eliminar tabla
    op.drop_table('actor_reports')
    
    # Eliminar ENUM
    report_type_enum = postgresql.ENUM('weekly', 'daily', name='reporttype')
    report_type_enum.drop(op.get_bind(), checkfirst=True)