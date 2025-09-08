import mysql.connector
from config import Config

def get_db_connection():
    """Retourne une connexion à la base de données"""
    return mysql.connector.connect(**Config.DB_CONFIG)

def create_database():
    """Crée la base de données et les tables nécessaires"""
    conn = mysql.connector.connect(
        host=Config.DB_CONFIG['host'],
        user=Config.DB_CONFIG['user'],
        password=Config.DB_CONFIG['password']
    )
    cursor = conn.cursor()
    
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {Config.DB_CONFIG['database']}")
    cursor.execute(f"USE {Config.DB_CONFIG['database']}")
    
    # ... (le reste de la fonction create_database reste inchangé)
    
    print("Base de données et tables créées avec succès!")

def install_demo_data():
    """Installer les données de démonstration"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        print("Installation des données de démonstration...")
        
        # 1. Nettoyer les tables existantes
        print("Nettoyage des tables existantes...")
        tables = ['criteres', 'qualite_references', 'champs', 'domaines', 'journaux_qualite']
        for table in tables:
            cursor.execute(f"DELETE FROM {table}")
        
        # 2. Insertion des domaines
        print("Insertion des domaines...")
        domaines = [
            ('D', 'Accompagnement des étudiants et vie estudiantine', 'Domaine dédié à l\'accompagnement des étudiants et à la vie estudiantine'),
            ('F', 'Formation et enseignement', 'Domaine relatif à la formation et à l\'enseignement'),
            ('R', 'Recherche scientifique', 'Domaine concernant la recherche scientifique')
        ]
        
        for code, titre, description in domaines:
            cursor.execute(
                "INSERT INTO domaines (code, titre, description) VALUES (%s, %s, %s)",
                (code, titre, description)
            )
        
        # ... (le reste de la fonction install_demo_data reste inchangé)
        
        conn.commit()
        print("Données de démonstration installées avec succès!")
        return True
        
    except Exception as e:
        print(f"Erreur lors de l'installation: {e}")
        conn.rollback()
        return False
        
    finally:
        cursor.close()
        conn.close()

def reset_database():
    """Réinitialiser complètement la base de données"""
    conn = mysql.connector.connect(
        host=Config.DB_CONFIG['host'],
        user=Config.DB_CONFIG['user'],
        password=Config.DB_CONFIG['password']
    )
    cursor = conn.cursor()
    
    try:
        # Supprimer et recréer la base
        cursor.execute(f"DROP DATABASE IF EXISTS {Config.DB_CONFIG['database']}")
        cursor.execute(f"CREATE DATABASE {Config.DB_CONFIG['database']}")
        conn.commit()
        
        # Recréer les tables
        create_database()
        
        print("Base de données réinitialisée avec succès!")
        return True
        
    except Exception as e:
        print(f"Erreur lors de la réinitialisation: {e}")
        return False
        
    finally:
        cursor.close()
        conn.close()