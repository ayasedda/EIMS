import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database_mysql import Database

class DataManager:
    def __init__(self):
        self.db = Database()
    
    def export_to_csv(self, df, filename="company_data.csv"):
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        return filename
    
    def export_to_excel(self, df, filename="company_data.xlsx"):
        df.to_excel(filename, index=False, engine='openpyxl')
        return filename
    
    def create_department_chart(self, df):
        dept_counts = df['department'].value_counts()
        fig = px.bar(
            x=dept_counts.index,
            y=dept_counts.values,
            labels={'x': 'Department', 'y': 'Number of Employees'},
            title='Employee Distribution by Department',
            color=dept_counts.values,
            color_continuous_scale='Blues'
        )
        fig.update_layout(
            xaxis_title="Department",
            yaxis_title="Number of Employees",
            showlegend=False
        )
        return fig
    
    def create_salary_chart(self, df):
        avg_salary = df.groupby('department')['salary'].mean().sort_values(ascending=False)
        fig = px.bar(
            x=avg_salary.index,
            y=avg_salary.values,
            labels={'x': 'Department', 'y': 'Average Salary'},
            title='Average Salary by Department',
            color=avg_salary.values,
            color_continuous_scale='Greens'
        )
        fig.update_layout(
            xaxis_title="Department",
            yaxis_title="Average Salary ($)",
            showlegend=False
        )
        return fig
    
    def create_status_pie_chart(self, df):
        status_counts = df['status'].value_counts()
        fig = px.pie(
            values=status_counts.values,
            names=status_counts.index,
            title='Employee Status Distribution',
            color_discrete_sequence=px.colors.sequential.RdBu
        )
        return fig
    
    def create_position_chart(self, df):
        position_counts = df['position'].value_counts().head(10)
        fig = px.bar(
            x=position_counts.values,
            y=position_counts.index,
            orientation='h',
            labels={'x': 'Count', 'y': 'Position'},
            title='Top 10 Most Common Positions',
            color=position_counts.values,
            color_continuous_scale='Oranges'
        )
        fig.update_layout(
            xaxis_title="Number of Employees",
            yaxis_title="Position",
            showlegend=False
        )
        return fig