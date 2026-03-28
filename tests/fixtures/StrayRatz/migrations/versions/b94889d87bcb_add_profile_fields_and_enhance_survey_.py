"""Add profile fields and enhance survey model

Revision ID: b94889d87bcb
Revises: 
Create Date: 2023-07-03 02:54:29.889991

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b94889d87bcb'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add profile fields to user table
    op.add_column('user', sa.Column('first_name', sa.String(length=64), nullable=True))
    op.add_column('user', sa.Column('last_name', sa.String(length=64), nullable=True))
    op.add_column('user', sa.Column('bio', sa.Text(), nullable=True))
    op.add_column('user', sa.Column('location', sa.String(length=128), nullable=True))
    op.add_column('user', sa.Column('fitness_goals', sa.String(length=128), nullable=True))
    op.add_column('user', sa.Column('fitness_level', sa.String(length=32), nullable=True))
    
    # Add enhanced fields to survey table
    op.add_column('survey', sa.Column('effectiveness_rating', sa.Integer(), nullable=True))
    op.add_column('survey', sa.Column('value_rating', sa.Integer(), nullable=True))
    op.add_column('survey', sa.Column('convenience_rating', sa.Integer(), nullable=True))
    op.add_column('survey', sa.Column('specific_needs', sa.Text(), nullable=True))
    op.add_column('survey', sa.Column('pain_points', sa.Text(), nullable=True))
    op.add_column('survey', sa.Column('expected_benefits', sa.Text(), nullable=True))
    op.add_column('survey', sa.Column('purchase_likelihood', sa.Integer(), nullable=True))


def downgrade():
    # Remove enhanced fields from survey table
    op.drop_column('survey', 'purchase_likelihood')
    op.drop_column('survey', 'expected_benefits')
    op.drop_column('survey', 'pain_points')
    op.drop_column('survey', 'specific_needs')
    op.drop_column('survey', 'convenience_rating')
    op.drop_column('survey', 'value_rating')
    op.drop_column('survey', 'effectiveness_rating')
    
    # Remove profile fields from user table
    op.drop_column('user', 'fitness_level')
    op.drop_column('user', 'fitness_goals')
    op.drop_column('user', 'location')
    op.drop_column('user', 'bio')
    op.drop_column('user', 'last_name')
    op.drop_column('user', 'first_name')
