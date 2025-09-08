from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import get_db_connection, create_database
from config import Config
import mysql.connector
import json
from datetime import datetime
import os
from flask import send_file
import tempfile
import shutil
import subprocess
from database import install_demo_data, reset_database
import PyPDF2
from flask import request, jsonify

app = Flask(__name__)
app.config.from_object(Config)

# Initialisation de la base de données avant de lancer le serveur
with app.app_context():
    create_database()

# téléchargement de la base de données de démonstration
@app.route('/download-demo-db')
def download_demo_db():
    """Télécharger la base de données de démonstration"""
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    temp_dir = None
    try:
        # Créer un répertoire temporaire
        temp_dir = tempfile.mkdtemp()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"smq_database_backup_{timestamp}.sql"
        backup_file = os.path.join(temp_dir, filename)
        
        # Configuration de la commande mysqldump
        db_config = Config.DB_CONFIG
        cmd = [
            'mysqldump',
            f"--user={db_config['user']}",
            f"--password={db_config['password']}",
            f"--host={db_config['host']}",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--events",
            db_config['database']
        ]
        
        print(f"Exécution de la commande: {' '.join(cmd[:3])} [password hidden] { ' '.join(cmd[4:])}")
        
        # Exécuter mysqldump
        with open(backup_file, 'w', encoding='utf-8') as f:
            process = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            _, stderr = process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.strip() if stderr else "Erreur inconnue avec mysqldump"
            flash(f'Erreur lors de la sauvegarde: {error_msg}', 'error')
            return redirect(url_for('dashboard'))
        
        # Vérifier le fichier de sortie
        if not os.path.exists(backup_file) or os.path.getsize(backup_file) == 0:
            flash('La sauvegarde a généré un fichier vide', 'error')
            return redirect(url_for('dashboard'))
        
        # Envoyer le fichier
        response = send_file(
            backup_file,
            as_attachment=True,
            download_name=filename,
            mimetype='application/sql'
        )
        
        # Nettoyage après l'envoi
        @response.call_on_close
        def cleanup_temp_dir():
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        
        return response
        
    except subprocess.SubprocessError as e:
        flash(f'Erreur d exécution de mysqldump: {str(e)}', 'error')
    except Exception as e:
        flash(f'Erreur inattendue: {str(e)}', 'error')
    finally:
        # Nettoyage en cas d'erreur
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    return redirect(url_for('dashboard'))
@app.route('/install-demo-data')
def install_demo_route():
    """Installer les données de démonstration"""
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    try:
        success = install_demo_data()
        
        if success:
            flash('Données de démonstration installées avec succès!', 'success')
        else:
            flash('Erreur lors de l\'installation des données de démonstration', 'error')
            
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/reset-demo-data')
def reset_demo_data():
    """Réinitialiser complètement avec données de démo"""
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    try:
        # 1. Réinitialiser la base
        reset_success = reset_database()
        
        if not reset_success:
            flash('Erreur lors de la réinitialisation de la base', 'error')
            return redirect(url_for('dashboard'))
        
        # 2. Installer les données de démo
        demo_success = install_demo_data()
        
        if demo_success:
            flash('Base de données réinitialisée avec les données de démonstration!', 'success')
        else:
            flash('Erreur lors de l\'installation des données de démonstration', 'error')
            
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))
# Routes d'authentification
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            flash('Connexion réussie!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Identifiants incorrects', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('login'))

# Routes de gestion des domaines
@app.route('/domaines')
def domaines():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM domaines ORDER BY code")
    domaines_list = cursor.fetchall()
    
    for domaine in domaines_list:
        cursor.execute("""
        SELECT c.*, 
               (SELECT COUNT(*) FROM qualite_references r 
                JOIN champs c2 ON r.champ_id = c2.id 
                WHERE c2.domaine_id = %s) as nb_references
        FROM champs c 
        WHERE c.domaine_id = %s 
        ORDER BY c.code
        """, (domaine['id'], domaine['id']))
        domaine['champs'] = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('domaines.html', domaines=domaines_list)

@app.route('/gestion-domaines')
def gestion_domaines():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM domaines ORDER BY code")
    domaines_list = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('domaines.html', domaines=domaines_list)

@app.route('/ajouter-domaine', methods=['GET', 'POST'])
def ajouter_domaine():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "INSERT INTO domaines (code, titre, description) VALUES (%s, %s, %s)",
                (code, titre, description)
            )
            conn.commit()
            flash('Domaine ajouté avec succès!', 'success')
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('domaines'))
    
    return render_template('ajouter_domaine.html')

@app.route('/modifier-domaine/<int:domaine_id>', methods=['GET', 'POST'])
def modifier_domaine(domaine_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        try:
            cursor.execute(
                "UPDATE domaines SET code = %s, titre = %s, description = %s WHERE id = %s",
                (code, titre, description, domaine_id)
            )
            conn.commit()
            flash('Domaine modifié avec succès!', 'success')
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('domaines'))
    
    cursor.execute("SELECT * FROM domaines WHERE id = %s", (domaine_id,))
    domaine = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    if not domaine:
        flash('Domaine non trouvé', 'error')
        return redirect(url_for('gestion_domaines'))
    
    return render_template('modifier_domaine.html', domaine=domaine)

@app.route('/supprimer-domaine/<int:domaine_id>')
def supprimer_domaine(domaine_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # D'abord supprimer les journaux liés
        cursor.execute("""
            DELETE FROM journaux_qualite 
            WHERE reference_id IN (
                SELECT r.id 
                FROM qualite_references r
                JOIN champs c ON r.champ_id = c.id 
                WHERE c.domaine_id = %s
            )
        """, (domaine_id,))
        
        # Puis supprimer les références
        cursor.execute("""
            DELETE FROM qualite_references 
            WHERE champ_id IN (
                SELECT id FROM champs WHERE domaine_id = %s
            )
        """, (domaine_id,))
        
        # Puis supprimer les champs
        cursor.execute("DELETE FROM champs WHERE domaine_id = %s", (domaine_id,))
        
        # Enfin supprimer le domaine
        cursor.execute("DELETE FROM domaines WHERE id = %s", (domaine_id,))
        
        conn.commit()
        flash('Domaine et toutes ses données associées supprimés avec succès!', 'success')
        
    except mysql.connector.Error as err:
        flash(f'Erreur: {err}', 'error')
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('domaines'))

# Routes de gestion des champs
@app.route('/gestion-champs/<int:domaine_id>')
def gestion_champs(domaine_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM domaines WHERE id = %s", (domaine_id,))
    domaine = cursor.fetchone()
    
    if not domaine:
        flash('Domaine non trouvé', 'error')
        return redirect(url_for('gestion_domaines'))
    
    cursor.execute("SELECT * FROM champs WHERE domaine_id = %s ORDER BY code", (domaine_id,))
    champs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('gestion_champs.html', domaine=domaine, champs=champs)

@app.route('/supprimer-champ/<int:champ_id>')
def supprimer_champ(champ_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Récupérer l'ID du domaine avant suppression pour la redirection
        cursor.execute("SELECT domaine_id FROM champs WHERE id = %s", (champ_id,))
        champ = cursor.fetchone()
        
        if not champ:
            flash('Champ non trouvé', 'error')
            return redirect(url_for('gestion_domaines'))
        
        # 1. D'abord supprimer les journaux liés aux références de ce champ
        cursor.execute("""
            DELETE FROM journaux_qualite 
            WHERE reference_id IN (
                SELECT id FROM qualite_references WHERE champ_id = %s
            )
        """, (champ_id,))
        
        # 2. Puis supprimer les références de ce champ
        cursor.execute("DELETE FROM qualite_references WHERE champ_id = %s", (champ_id,))
        
        # 3. Enfin supprimer le champ
        cursor.execute("DELETE FROM champs WHERE id = %s", (champ_id,))
        
        conn.commit()
        flash('Champ et toutes ses données associées supprimés avec succès!', 'success')
        
    except mysql.connector.Error as err:
        flash(f'Erreur: {err}', 'error')
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('gestion_champs', domaine_id=champ['domaine_id']))

@app.route('/modifier-champ/<int:champ_id>', methods=['GET', 'POST'])
def modifier_champ(champ_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer les informations du champ et du domaine
    cursor.execute("""
    SELECT c.*, d.code as domaine_code, d.titre as domaine_titre 
    FROM champs c 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE c.id = %s
    """, (champ_id,))
    
    champ = cursor.fetchone()
    
    if not champ:
        flash('Champ non trouvé', 'error')
        return redirect(url_for('domaines'))
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        try:
            cursor.execute(
                "UPDATE champs SET code = %s, titre = %s, description = %s WHERE id = %s",
                (code, titre, description, champ_id)
            )
            conn.commit()
            flash('Champ modifié avec succès!', 'success')
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('gestion_champs', domaine_id=champ['domaine_id']))
    
    cursor.close()
    conn.close()
    
    return render_template('modifier_champ.html', champ=champ)
@app.route('/ajouter-champ/<int:domaine_id>', methods=['GET', 'POST'])
def ajouter_champ(domaine_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM domaines WHERE id = %s", (domaine_id,))
    domaine = cursor.fetchone()
    
    if not domaine:
        flash('Domaine non trouvé', 'error')
        return redirect(url_for('domaines'))
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        try:
            cursor.execute(
                "INSERT INTO champs (domaine_id, code, titre, description) VALUES (%s, %s, %s, %s)",
                (domaine_id, code, titre, description)
            )
            conn.commit()
            flash('Champ ajouté avec succès!', 'success')
            return redirect(url_for('gestion_champs', domaine_id=domaine_id))
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
    
    cursor.close()
    conn.close()
    
    return render_template('ajouter_champ.html', domaine=domaine)

# Routes de gestion des références
@app.route('/gestion-references/<int:champ_id>')
def gestion_references(champ_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
    SELECT c.*, d.code as domaine_code, d.titre as domaine_titre 
    FROM champs c 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE c.id = %s
    """, (champ_id,))
    champ = cursor.fetchone()
    
    if not champ:
        flash('Champ non trouvé', 'error')
        return redirect(url_for('domaines'))
    
    cursor.execute("SELECT * FROM qualite_references WHERE champ_id = %s ORDER BY code", (champ_id,))
    references = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('gestion_references.html', champ=champ, references=references)

@app.route('/supprimer-reference/<int:reference_id>')
def supprimer_reference(reference_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer l'ID du champ avant suppression pour la redirection
    cursor.execute("SELECT champ_id FROM qualite_references WHERE id = %s", (reference_id,))
    reference = cursor.fetchone()
    
    if not reference:
        flash('Référence non trouvée', 'error')
        return redirect(url_for('domaines'))
    
    try:
        # La suppression en cascade devrait s'occuper des critères associés
        # grâce aux FOREIGN KEY avec ON DELETE CASCADE
        cursor.execute("DELETE FROM qualite_references WHERE id = %s", (reference_id,))
        conn.commit()
        flash('Référence supprimée avec succès!', 'success')
    except mysql.connector.Error as err:
        flash(f'Erreur: {err}', 'error')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('gestion_references', champ_id=reference['champ_id']))

@app.route('/modifier-reference/<int:reference_id>', methods=['GET', 'POST'])
def modifier_reference(reference_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer les informations de la référence et du champ
    cursor.execute("""
    SELECT r.*, c.code as champ_code, c.titre as champ_titre,
           d.code as domaine_code, d.titre as domaine_titre
    FROM qualite_references r
    JOIN champs c ON r.champ_id = c.id
    JOIN domaines d ON c.domaine_id = d.id
    WHERE r.id = %s
    """, (reference_id,))
    
    reference = cursor.fetchone()
    
    if not reference:
        flash('Référence non trouvée', 'error')
        return redirect(url_for('domaines'))
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        try:
            cursor.execute(
                "UPDATE qualite_references SET code = %s, titre = %s, description = %s WHERE id = %s",
                (code, titre, description, reference_id)
            )
            conn.commit()
            flash('Référence modifiée avec succès!', 'success')
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('gestion_references', champ_id=reference['champ_id']))
    
    cursor.close()
    conn.close()
    
    return render_template('modifier_reference.html', reference=reference)

@app.route('/ajouter-reference/<int:champ_id>', methods=['GET', 'POST'])
def ajouter_reference(champ_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
    SELECT c.*, d.code as domaine_code 
    FROM champs c 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE c.id = %s
    """, (champ_id,))
    champ = cursor.fetchone()
    
    if not champ:
        flash('Champ non trouvé', 'error')
        return redirect(url_for('domaines'))
    
    if request.method == 'POST':
        code = request.form['code']
        titre = request.form['titre']
        description = request.form['description']
        
        try:
            cursor.execute(
                "INSERT INTO qualite_references (champ_id, code, titre, description) VALUES (%s, %s, %s, %s)",
                (champ_id, code, titre, description)
            )
            conn.commit()
            flash('Référence ajoutée avec succès!', 'success')
            return redirect(url_for('gestion_references', champ_id=champ_id))
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
    
    cursor.close()
    conn.close()
    
    return render_template('ajouter_reference.html', champ=champ)

# Routes de gestion des critères
@app.route('/gestion-criteres/<int:reference_id>')
def gestion_criteres(reference_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
    SELECT r.*, c.code as champ_code, c.titre as champ_titre, d.code as domaine_code 
    FROM qualite_references r 
    JOIN champs c ON r.champ_id = c.id 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE r.id = %s
    """, (reference_id,))
    reference = cursor.fetchone()
    
    if not reference:
        flash('Référence non trouvée', 'error')
        return redirect(url_for('domaines'))
    
    cursor.execute("SELECT * FROM criteres WHERE reference_id = %s ORDER BY numero", (reference_id,))
    criteres = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('gestion_criteres.html', reference=reference, criteres=criteres)

@app.route('/ajouter-critere/<int:reference_id>', methods=['GET', 'POST'])
def ajouter_critere(reference_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
    SELECT r.*, c.code as champ_code, d.code as domaine_code 
    FROM qualite_references r 
    JOIN champs c ON r.champ_id = c.id 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE r.id = %s
    """, (reference_id,))
    reference = cursor.fetchone()
    
    if not reference:
        flash('Référence non trouvée', 'error')
        return redirect(url_for('domaines'))
    
    if request.method == 'POST':
        numero = request.form['numero']
        description = request.form['description']
        
        try:
            cursor.execute(
                "INSERT INTO criteres (reference_id, numero, description) VALUES (%s, %s, %s)",
                (reference_id, numero, description)
            )
            conn.commit()
            flash('Critère ajouté avec succès!', 'success')
            return redirect(url_for('gestion_criteres', reference_id=reference_id))
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
    
    cursor.close()
    conn.close()
    
    return render_template('ajouter_critere.html', reference=reference)

@app.route('/modifier-critere/<int:critere_id>', methods=['GET', 'POST'])
def modifier_critere(critere_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer les informations du critère et de la référence
    cursor.execute("""
    SELECT cr.*, r.code as reference_code, r.titre as reference_titre,
           c.code as champ_code, d.code as domaine_code
    FROM criteres cr
    JOIN qualite_references r ON cr.reference_id = r.id
    JOIN champs c ON r.champ_id = c.id
    JOIN domaines d ON c.domaine_id = d.id
    WHERE cr.id = %s
    """, (critere_id,))
    
    critere = cursor.fetchone()
    
    if not critere:
        flash('Critère non trouvé', 'error')
        return redirect(url_for('gestion_domaines'))
    
    if request.method == 'POST':
        numero = request.form['numero']
        description = request.form['description']
        
        try:
            cursor.execute(
                "UPDATE criteres SET numero = %s, description = %s WHERE id = %s",
                (numero, description, critere_id)
            )
            conn.commit()
            flash('Critère modifié avec succès!', 'success')
        except mysql.connector.Error as err:
            flash(f'Erreur: {err}', 'error')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('gestion_criteres', reference_id=critere['reference_id']))
    
    cursor.close()
    conn.close()
    
    return render_template('modifier_critere.html', critere=critere)
@app.route('/supprimer-critere/<int:critere_id>', methods=['POST'])
def supprimer_critere(critere_id):
    # Vérification des droits
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer l'ID de la référence avant suppression
    cursor.execute("SELECT reference_id FROM criteres WHERE id = %s", (critere_id,))
    critere = cursor.fetchone()
    
    if not critere:
        flash('Critère non trouvé', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('gestion_domaines'))
    
    try:
        cursor.execute("DELETE FROM criteres WHERE id = %s", (critere_id,))
        conn.commit()
        flash('Critère supprimé avec succès!', 'success')
    except mysql.connector.Error as err:
        conn.rollback()
        flash(f'Erreur: {err}', 'error')
    finally:
        cursor.close()
        conn.close()
    
    # Redirige vers la liste des critères de la référence
    return redirect(url_for('gestion_criteres', reference_id=critere['reference_id']))

# Routes de gestion des journaux de qualité
# Routes de gestion des journaux de qualité
@app.route('/journal/<int:reference_id>', methods=['GET', 'POST'])
def journal(reference_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Récupérer les informations de la référence
        cursor.execute("""
        SELECT r.*, c.titre as champ_titre, d.titre as domaine_titre 
        FROM qualite_references r 
        JOIN champs c ON r.champ_id = c.id 
        JOIN domaines d ON c.domaine_id = d.id 
        WHERE r.id = %s
        """, (reference_id,))
        
        reference = cursor.fetchone()
        
        if not reference:
            flash('Référence non trouvée', 'error')
            return redirect(url_for('domaines'))
        
        journal_data = None
        
        if request.method == 'GET':
            # Récupérer le journal existant
            cursor.execute("""
            SELECT * FROM journaux_qualite 
            WHERE reference_id = %s 
            ORDER BY created_at DESC LIMIT 1
            """, (reference_id,))
            
            journal_data = cursor.fetchone()
            
            if journal_data:
                # Décoder les données JSON existantes
                journal_data['objectifs'] = json.loads(journal_data['objectifs']) if journal_data.get('objectifs') else []
                journal_data['engagements'] = json.loads(journal_data['engagements']) if journal_data.get('engagements') else []
                journal_data['actions_suivi'] = json.loads(journal_data['actions']) if journal_data.get('actions') else []
                journal_data['non_conformites'] = json.loads(journal_data['non_conformites']) if journal_data.get('non_conformites') else []
                journal_data['indicateurs'] = json.loads(journal_data['indicateurs']) if journal_data.get('indicateurs') else []
                journal_data['plans_amelioration'] = json.loads(journal_data['plans']) if journal_data.get('plans') else []
        
        elif request.method == 'POST':
            # === RÉCUPÉRATION DES DONNÉES ===
            action = request.form.get('action', 'save_draft')
            statut = 'soumis' if action == 'submit' else 'brouillon'
            
            # Données de base
            faculte = request.form.get('faculte', 'Faculté Polydisciplinaire de Ouarzazate')
            periode_debut = request.form.get('periode_debut', '')
            periode_fin = request.form.get('periode_fin', '')
            observations = request.form.get('observations', '')
            
            # Revues
            revue_date = request.form.get('revue_date', '')
            revue_participants = request.form.get('revue_participants', '')
            revue_decisions = request.form.get('revue_decisions', '')
            
            # Données des tableaux
            objectifs = [obj for obj in request.form.getlist('objectifs[]') if obj and obj.strip()]
            engagements = [eng for eng in request.form.getlist('engagements[]') if eng and eng.strip()]
            
            # Actions de suivi
            actions_suivi = []
            dates_actions = request.form.getlist('actions_date[]')
            for i in range(len(dates_actions)):
                if dates_actions[i] and dates_actions[i].strip():
                    actions_suivi.append({
                        'date': dates_actions[i],
                        'processus': request.form.getlist('actions_processus[]')[i],
                        'description': request.form.getlist('actions_description[]')[i],
                        'responsable': request.form.getlist('actions_responsable[]')[i],
                        'statut': request.form.getlist('actions_statut[]')[i] or 'planifié'
                    })
            
            # Non-conformités
            non_conformites = []
            dates_nc = request.form.getlist('nc_date[]')
            for i in range(len(dates_nc)):
                if dates_nc[i] and dates_nc[i].strip():
                    non_conformites.append({
                        'date': dates_nc[i],
                        'description': request.form.getlist('nc_description[]')[i],
                        'cause': request.form.getlist('nc_cause[]')[i],
                        'action': request.form.getlist('nc_action[]')[i],
                        'responsable': request.form.getlist('nc_responsable[]')[i],
                        'statut': request.form.getlist('nc_statut[]')[i] or 'ouvert'
                    })
            
            # Indicateurs
            indicateurs = []
            noms_indicateurs = request.form.getlist('indicateurs_nom[]')
            for i in range(len(noms_indicateurs)):
                if noms_indicateurs[i] and noms_indicateurs[i].strip():
                    indicateurs.append({
                        'nom': noms_indicateurs[i],
                        'cible': request.form.getlist('indicateurs_cible[]')[i],
                        'actuel': request.form.getlist('indicateurs_actuel[]')[i],
                        'analyse': request.form.getlist('indicateurs_analyse[]')[i]
                    })
            
            # Plans d'amélioration
            plans_amelioration = []
            actions_plan = request.form.getlist('plan_action[]')
            for i in range(len(actions_plan)):
                if actions_plan[i] and actions_plan[i].strip():
                    plans_amelioration.append({
                        'action': actions_plan[i],
                        'objectif': request.form.getlist('plan_objectif[]')[i],
                        'responsable': request.form.getlist('plan_responsable[]')[i],
                        'delai': request.form.getlist('plan_delai[]')[i]
                    })
            
            # === PRÉPARATION DES DONNÉES ===
            actions_json = json.dumps(actions_suivi, ensure_ascii=False) if actions_suivi else '[]'
            non_conformites_json = json.dumps(non_conformites, ensure_ascii=False) if non_conformites else '[]'
            indicateurs_json = json.dumps(indicateurs, ensure_ascii=False) if indicateurs else '[]'
            plans_json = json.dumps(plans_amelioration, ensure_ascii=False) if plans_amelioration else '[]'
            
            # === VÉRIFICATION SI JOURNAL EXISTE ===
            cursor.execute("SELECT * FROM journaux_qualite WHERE reference_id = %s", (reference_id,))
            existing_journal = cursor.fetchone()
            
            # === EXÉCUTION DE LA REQUÊTE ===
            if existing_journal:
                # Mise à jour du journal existant
                query = """
                UPDATE journaux_qualite 
                SET faculte=%s, periode_debut=%s, periode_fin=%s,
                    revue_date=%s, revue_participants=%s, revue_decisions=%s,
                    objectifs=%s, engagements=%s, actions=%s, non_conformites=%s,
                    indicateurs=%s, plans=%s, observations=%s,
                    updated_by=%s, statut=%s, version=version+1, updated_at=NOW()
                WHERE id=%s
                """
                params = (
                    faculte, periode_debut, periode_fin,
                    revue_date, revue_participants, revue_decisions,
                    json.dumps(objectifs), json.dumps(engagements), 
                    actions_json, non_conformites_json, 
                    indicateurs_json, plans_json,
                    observations, session['user_id'], statut, existing_journal['id']
                )
            else:
                # Création d'un nouveau journal
                query = """
                INSERT INTO journaux_qualite 
                (reference_id, domaine, champ, faculte, periode_debut, periode_fin,
                 revue_date, revue_participants, revue_decisions,
                 objectifs, engagements, actions, non_conformites, 
                 indicateurs, plans, observations, created_by, updated_by, statut)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    reference_id, reference['domaine_titre'], reference['champ_titre'], 
                    faculte, periode_debut, periode_fin,
                    revue_date, revue_participants, revue_decisions,
                    json.dumps(objectifs), json.dumps(engagements), 
                    actions_json, non_conformites_json, 
                    indicateurs_json, plans_json,
                    observations, session['user_id'], session['user_id'], statut
                )
            
            cursor.execute(query, params)
            conn.commit()
            
            message = 'Journal soumis avec succès!' if statut == 'soumis' else 'Brouillon enregistré avec succès!'
            flash(message, 'success')
            return redirect(url_for('journal', reference_id=reference_id))
            
    except Exception as err:
        flash(f'Erreur lors de l\'enregistrement: {str(err)}', 'error')
        conn.rollback()
        return redirect(url_for('journal', reference_id=reference_id))
    finally:
        cursor.close()
        conn.close()
    
    return render_template('creer_journal.html', reference=reference, journal_data=journal_data)

@app.route('/consulter-journal/<int:journal_id>')
def consulter_journal(journal_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Récupérer le journal avec toutes les informations
        cursor.execute("""
        SELECT jq.*, r.titre as reference_titre, r.code as reference_code,
               c.titre as champ_titre, d.titre as domaine_titre,
               u.nom as responsable_nom, u.prenom as responsable_prenom
        FROM journaux_qualite jq
        JOIN qualite_references r ON jq.reference_id = r.id
        JOIN champs c ON r.champ_id = c.id
        JOIN domaines d ON c.domaine_id = d.id
        LEFT JOIN users u ON jq.created_by = u.id
        WHERE jq.id = %s
        """, (journal_id,))
        
        journal = cursor.fetchone()
        
        if not journal:
            flash('Journal non trouvé', 'error')
            return redirect(url_for('domaines'))
        
        # Convertir les données JSON en listes
        journal['objectifs_list'] = json.loads(journal['objectifs']) if journal.get('objectifs') else []
        journal['engagements_list'] = json.loads(journal['engagements']) if journal.get('engagements') else []
        journal['actions_list'] = json.loads(journal['actions']) if journal.get('actions') else []
        journal['non_conformites_list'] = json.loads(journal['non_conformites']) if journal.get('non_conformites') else []
        journal['indicateurs_list'] = json.loads(journal['indicateurs']) if journal.get('indicateurs') else []
        journal['plans_list'] = json.loads(journal['plans']) if journal.get('plans') else []
        
    except Exception as e:
        flash(f'Erreur lors de la récupération du journal: {str(e)}', 'error')
        return redirect(url_for('domaines'))
    
    finally:
        cursor.close()
        conn.close()
    
    return render_template('consulter_journal.html', journal=journal)




# Route pour voir les détails d'un champ
@app.route('/voir-champ/<int:champ_id>')
def voir_champ(champ_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Récupérer les informations du champ
    cursor.execute("""
    SELECT c.*, d.code as domaine_code, d.titre as domaine_titre 
    FROM champs c 
    JOIN domaines d ON c.domaine_id = d.id 
    WHERE c.id = %s
    """, (champ_id,))
    champ = cursor.fetchone()
    
    if not champ:
        flash('Champ non trouvé', 'error')
        return redirect(url_for('domaines'))
    
    # Récupérer les références associées à ce champ
    cursor.execute("""
    SELECT r.*, 
           (SELECT COUNT(*) FROM criteres WHERE reference_id = r.id) as nb_criteres
    FROM qualite_references r 
    WHERE r.champ_id = %s 
    ORDER BY r.code
    """, (champ_id,))
    references = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('voir_champ.html', champ=champ, references=references)
#
@app.route('/import-pdf-data', methods=['POST'])
def import_pdf_data():
    """Importer les données depuis un fichier PDF"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Accès non autorisé'})
    
    if 'pdfFile' not in request.files:
        return jsonify({'success': False, 'message': 'Aucun fichier PDF fourni'})
    
    pdf_file = request.files['pdfFile']
    if pdf_file.filename == '':
        return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
    
    if not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'message': 'Le fichier doit être au format PDF'})
    
    include_journals = request.form.get('includeJournals', 'true') == 'true'
    overwrite_existing = request.form.get('overwriteExisting', 'true') == 'true'
    
    try:
        # Créer un fichier temporaire
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            pdf_file.save(temp_file.name)
            
            # Lire le contenu du PDF
            pdf_reader = PyPDF2.PdfReader(temp_file.name)
            text_content = ""
            
            for page in pdf_reader.pages:
                text_content += page.extract_text() + "\n"
            
            # Traiter le contenu du PDF et extraire les données
            # Cette partie dépend de la structure spécifique de votre PDF
            
            # Exemple d'extraction basique (à adapter selon votre format PDF)
            domain_data = extract_domain_data_from_pdf(text_content)
            
            if not domain_data:
                return jsonify({'success': False, 'message': 'Impossible d\'extraire les données du PDF'})
            
            # Insérer les données dans la base
            success = insert_domain_data(domain_data, include_journals, overwrite_existing)
            
            if success:
                return jsonify({'success': True, 'message': f'Domaine {domain_data["code"]} importé avec succès!'})
            else:
                return jsonify({'success': False, 'message': 'Erreur lors de l\'insertion des données'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur lors du traitement du PDF: {str(e)}'})
    
    finally:
        # Nettoyer le fichier temporaire
        if 'temp_file' in locals():
            os.unlink(temp_file.name)

def extract_domain_data_from_pdf(text_content):
    """Extraire les données du domaine depuis le texte du PDF"""
    # Implémentez la logique d'extraction spécifique à votre format PDF
    # Cette fonction doit parser le texte et retourner un dictionnaire structuré
    
    # Exemple de structure de retour attendue:
    domain_data = {
        'code': 'D',
        'titre': 'ACCOMPAGNEMENT DES ETUDIANTS ET VIE ESTUDIANTINE',
        'description': 'Domaine dédié à l\'accompagnement des étudiants et à la vie estudiantine',
        'champs': [
            {
                'code': 'D.I',
                'titre': 'Admission et orientation des étudiants',
                'references': [
                    {
                        'code': 'D.I.1',
                        'titre': 'L\'institution définit les qualifications des étudiants ciblés...',
                        'criteres': [
                            {'numero': 1, 'description': 'L\'institution admet les étudiants...'},
                            {'numero': 2, 'description': 'L\'institution dispose de procédures...'}
                        ],
                        'journal': {
                            'faculte': 'Faculté Polydisciplinaire de Ouarzazate',
                            'periode': 'Du 01/01/2024 au 01/01/2026',
                            'objectifs': ['Assurer l\'actualisation...', 'Renforcer l\'efficacité...'],
                            # ... autres données du journal
                        }
                    }
                ]
            }
        ]
    }
    
    return domain_data

def insert_domain_data(domain_data, include_journals, overwrite_existing):
    """Insérer les données du domaine dans la base de données"""
    # Implémentez la logique d'insertion dans la base de données
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if overwrite_existing:
            # Supprimer le domaine existant s'il existe
            cursor.execute("DELETE FROM domaines WHERE code = %s", (domain_data['code'],))
        
        # Insérer le domaine
        cursor.execute(
            "INSERT INTO domaines (code, titre, description) VALUES (%s, %s, %s)",
            (domain_data['code'], domain_data['titre'], domain_data['description'])
        )
        domaine_id = cursor.lastrowid
        
        # Insérer les champs
        for champ in domain_data.get('champs', []):
            cursor.execute(
                "INSERT INTO champs (domaine_id, code, titre, description) VALUES (%s, %s, %s, %s)",
                (domaine_id, champ['code'], champ['titre'], champ.get('description', ''))
            )
            champ_id = cursor.lastrowid
            
            # Insérer les références
            for reference in champ.get('references', []):
                cursor.execute(
                    "INSERT INTO qualite_references (champ_id, code, titre, description) VALUES (%s, %s, %s, %s)",
                    (champ_id, reference['code'], reference['titre'], reference.get('description', ''))
                )
                reference_id = cursor.lastrowid
                
                # Insérer les critères
                for critere in reference.get('criteres', []):
                    cursor.execute(
                        "INSERT INTO criteres (reference_id, numero, description) VALUES (%s, %s, %s)",
                        (reference_id, critere['numero'], critere['description'])
                    )
                
                # Insérer le journal si demandé
                if include_journals and 'journal' in reference:
                    journal = reference['journal']
                    cursor.execute(
                        """INSERT INTO journaux_qualite 
                        (reference_id, faculte, periode_debut, periode_fin, objectifs, engagements, 
                         actions, non_conformites, indicateurs, plans, observations, created_by, statut)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (reference_id, journal['faculte'], 
                         journal.get('periode_debut', ''), journal.get('periode_fin', ''),
                         json.dumps(journal.get('objectifs', [])), 
                         json.dumps(journal.get('engagements', [])),
                         json.dumps(journal.get('actions', [])), 
                         json.dumps(journal.get('non_conformites', [])),
                         json.dumps(journal.get('indicateurs', [])), 
                         json.dumps(journal.get('plans', [])),
                         journal.get('observations', ''), 
                         session['user_id'], 'soumis')
                    )
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"Erreur lors de l'insertion: {str(e)}")
        return False
        
    finally:
        cursor.close()
        conn.close()

#
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from io import BytesIO
import textwrap

@app.route('/download-domaine-pdf/<int:domaine_id>')
def download_domaine_pdf(domaine_id):
    """Télécharger les données d'un domaine au format PDF avec tous les détails des journaux"""
    if 'user_id' not in session:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Récupérer les informations du domaine
        cursor.execute("SELECT * FROM domaines WHERE id = %s", (domaine_id,))
        domaine = cursor.fetchone()
        
        if not domaine:
            flash('Domaine non trouvé', 'error')
            return redirect(url_for('gestion_domaines'))
        
        # Récupérer tous les champs du domaine
        cursor.execute("SELECT * FROM champs WHERE domaine_id = %s ORDER BY code", (domaine_id,))
        champs = cursor.fetchall()
        
        # Structure pour stocker toutes les données
        domaine_data = {
            'domaine': domaine,
            'champs': []
        }
        
        # Pour chaque champ, récupérer les références
        for champ in champs:
            cursor.execute("SELECT * FROM qualite_references WHERE champ_id = %s ORDER BY code", (champ['id'],))
            references = cursor.fetchall()
            
            champ_data = {
                'champ': champ,
                'references': []
            }
            
            # Pour chaque référence, récupérer les critères et journaux
            for reference in references:
                cursor.execute("SELECT * FROM criteres WHERE reference_id = %s ORDER BY numero", (reference['id'],))
                criteres = cursor.fetchall()
                
                # CORRECTION : Utiliser les colonnes correctes de la table users
                cursor.execute("""
                    SELECT jq.*, u.full_name as responsable 
                    FROM journaux_qualite jq 
                    LEFT JOIN users u ON jq.created_by = u.id 
                    WHERE jq.reference_id = %s 
                    ORDER BY jq.created_at DESC
                """, (reference['id'],))
                journaux = cursor.fetchall()
                
                # Décoder les données JSON pour chaque journal
                for journal in journaux:
                    if journal.get('objectifs'):
                        journal['objectifs_list'] = json.loads(journal['objectifs'])
                    if journal.get('engagements'):
                        journal['engagements_list'] = json.loads(journal['engagements'])
                    if journal.get('actions'):
                        journal['actions_list'] = json.loads(journal['actions'])
                    if journal.get('non_conformites'):
                        journal['non_conformites_list'] = json.loads(journal['non_conformites'])
                    if journal.get('indicateurs'):
                        journal['indicateurs_list'] = json.loads(journal['indicateurs'])
                    if journal.get('plans'):
                        journal['plans_list'] = json.loads(journal['plans'])
                    # Ajouter les revues et décisions si elles existent
                    if journal.get('revue_date') or journal.get('revue_participants') or journal.get('revue_decisions'):
                        journal['has_revue'] = True
                
                reference_data = {
                    'reference': reference,
                    'criteres': criteres,
                    'journaux': journaux
                }
                
                champ_data['references'].append(reference_data)
            
            domaine_data['champs'].append(champ_data)
        
        # Créer le PDF en mémoire
        buffer = BytesIO()
        pdf = SimpleDocTemplate(
            buffer, 
            pagesize=A4, 
            rightMargin=40, 
            leftMargin=40, 
            topMargin=40, 
            bottomMargin=40
        )
        
        # Styles améliorés avec couleurs personnalisées
        styles = getSampleStyleSheet()
        
        # Style pour le titre principal (ROUGE pour le domaine)
        styles.add(ParagraphStyle(
            name='MainTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,  # Centré
            textColor=colors.HexColor('#B22222'),  # Rouge brique
            fontName='Helvetica-Bold'
        ))
        
        # Style pour SYSTEME DE MANAGEMENT DE LA QUALITE uniquement (BLEU)
        styles.add(ParagraphStyle(
            name='SystemTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=10,
            alignment=1,  # Centré
            textColor=colors.HexColor('#1E3A8A'),  # Bleu foncé
            fontName='Helvetica-Bold'
        ))
        
        # Style pour les titres de section (VERT pour les champs)
        styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=styles['Heading2'],
            fontSize=14,
            spaceAfter=12,
            textColor=colors.HexColor('#228B22'),  # Vert forêt
            fontName='Helvetica-Bold'
        ))
        
        # Style pour les sous-titres
        styles.add(ParagraphStyle(
            name='SubTitle',
            parent=styles['Heading3'],
            fontSize=12,
            spaceAfter=6,
            textColor=colors.HexColor('#0F24E0'),  # Vert océan
            fontName='Helvetica-Bold'
        ))
        
        # Style pour le texte justifié
        styles.add(ParagraphStyle(
            name='Justified',
            parent=styles['BodyText'],
            alignment=4,  # Justifié
            spaceAfter=6
        ))
        
        # Style pour les en-têtes de tableau
        styles.add(ParagraphStyle(
            name='TableHeader',
            parent=styles['BodyText'],
            fontSize=9,
            textColor=colors.white,
            alignment=1,  # Centré
            fontName='Helvetica-Bold'
        ))
        
        # Style pour la première colonne (texte en noir)
        styles.add(ParagraphStyle(
            name='FirstColumnBlack',
            parent=styles['BodyText'],
            fontSize=9,
            alignment=0,
            textColor=colors.black,  # Texte en noir
            fontName='Helvetica-Bold'
        ))
        
        # Style pour la deuxième colonne
        styles.add(ParagraphStyle(
            name='SecondColumn',
            parent=styles['BodyText'],
            fontSize=9,
            alignment=0,
            textColor=colors.black
        ))
        
        # Style pour le contenu des tableaux
        styles.add(ParagraphStyle(
            name='TableCell',
            parent=styles['BodyText'],
            fontSize=8,
            alignment=0,  # Gauche
            spaceAfter=0
        ))
        
        # Contenu du PDF
        story = []
        
        # En-tête avec logo et titre
        logo_path = "static/images/logo.png"  # Chemin vers votre logo
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=80, height=80)
            story.append(logo)
        
        # Titre SYSTEME DE MANAGEMENT DE LA QUALITE en BLEU uniquement
        story.append(Paragraph("SYSTÈME DE MANAGEMENT DE LA QUALITÉ", styles['SystemTitle']))
        
        # Titre du domaine en ROUGE
        story.append(Paragraph(f"DOMAINE: {domaine_data['domaine']['code']} - {domaine_data['domaine']['titre']}", styles['MainTitle']))
        
        # Description du domaine
        if domaine_data['domaine']['description']:
            story.append(Paragraph("Description du Domaine:", styles['SubTitle']))
            story.append(Paragraph(domaine_data['domaine']['description'], styles['Justified']))
        
        story.append(Spacer(1, 20))
        
        # Parcourir tous les champs
        for champ_data in domaine_data['champs']:
            champ = champ_data['champ']
            
            # Titre du champ (VERT) - Ligne spécifique avec couleur verte
            story.append(Paragraph(f"CHAMP: {champ['code']} - {champ['titre']}", styles['SectionTitle']))
            
            # Description du champ
            if champ['description']:
                story.append(Paragraph("Description:", styles['SubTitle']))
                story.append(Paragraph(champ['description'], styles['Justified']))
            
            story.append(Spacer(1, 15))
            
            # Parcourir toutes les références
            for ref_data in champ_data['references']:
                reference = ref_data['reference']
                
                # Titre de la référence
                story.append(Paragraph(f"RÉFÉRENCE: {reference['code']} - {reference['titre']}", styles['SubTitle']))
                
                # Description de la référence
                if reference['description']:
                    story.append(Paragraph("Description:", styles['Heading4']))
                    story.append(Paragraph(reference['description'], styles['Justified']))
                
                # Afficher les critères
                if ref_data['criteres']:
                    story.append(Paragraph("CRITÈRES:", styles['Heading4']))
                    for critere in ref_data['criteres']:
                        story.append(Paragraph(f"{critere['numero']}. {critere['description']}", styles['Justified']))
                
                story.append(Spacer(1, 10))
                
                # Afficher les journaux COMPLETS
                if ref_data['journaux']:
                    story.append(Paragraph("JOURNAUX DE QUALITÉ:", styles['Heading4']))
                    
                    for journal in ref_data['journaux']:
                        # Informations de base du journal avec fond bleu clair pour l'en-tête
                        journal_header_style = [
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0EDEF5')),  # Bleu clair
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),  # Texte en noir
                            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, 0), 9),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ]
                        
                        journal_info = [
                            [Paragraph("Faculté:", styles['FirstColumnBlack']), Paragraph(journal['faculte'], styles['SecondColumn'])],
                            [Paragraph("Période:", styles['FirstColumnBlack']), Paragraph(f"{journal['periode_debut']} au {journal['periode_fin']}", styles['SecondColumn'])],
                            [Paragraph("Statut:", styles['FirstColumnBlack']), Paragraph(journal['statut'], styles['SecondColumn'])],
                            [Paragraph("Créé le:", styles['FirstColumnBlack']), Paragraph(str(journal['created_at']), styles['SecondColumn'])],
                            [Paragraph("Responsable:", styles['FirstColumnBlack']), Paragraph(journal.get('responsable', 'Non spécifié'), styles['SecondColumn'])]
                        ]
                        
                        journal_table = Table(journal_info, colWidths=[1.5*inch, 4*inch])
                        journal_table.setStyle(TableStyle(journal_header_style + [
                            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#E6F7FF')),  # Bleu très clair pour première colonne
                            ('BACKGROUND', (1, 1), (1, -1), colors.beige),  # Beige pour deuxième colonne
                            ('TEXTCOLOR', (0, 1), (0, -1), colors.black),  # Texte première colonne en noir
                            ('TEXTCOLOR', (1, 1), (1, -1), colors.black),  # Texte deuxième colonne en noir
                            ('FONTSIZE', (0, 1), (-1, -1), 9),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
                        ]))
                        story.append(journal_table)
                        
                        story.append(Spacer(1, 12))
                        
                        # 1. Objectifs et Engagements
                        story.append(Paragraph("1. OBJECTIFS ET ENGAGEMENTS QUALITÉ", styles['SubTitle']))
                        
                        if journal.get('objectifs_list'):
                            story.append(Paragraph("Objectifs de qualité pour la période:", styles['Heading4']))
                            for obj in journal['objectifs_list']:
                                if obj and obj.strip():
                                    story.append(Paragraph(f"• {obj}", styles['Justified']))
                            story.append(Spacer(1, 8))
                        
                        if journal.get('engagements_list'):
                            story.append(Paragraph("Engagements de la direction:", styles['Heading4']))
                            for eng in journal['engagements_list']:
                                if eng and eng.strip():
                                    story.append(Paragraph(f"• {eng}", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # 2. Actions de suivi
                        story.append(Paragraph("2. ACTIONS DE SUIVI ET D'AMÉLIORATION", styles['SubTitle']))
                        
                        if journal.get('actions_list') and len(journal['actions_list']) > 0:
                            actions_data = [
                                [Paragraph("Date", styles['TableHeader']), 
                                 Paragraph("Processus", styles['TableHeader']), 
                                 Paragraph("Description", styles['TableHeader']), 
                                 Paragraph("Responsable", styles['TableHeader']), 
                                 Paragraph("Statut", styles['TableHeader'])]
                            ]
                            
                            for action in journal['actions_list']:
                                if isinstance(action, dict):
                                    actions_data.append([
                                        Paragraph(action.get('date', ''), styles['TableCell']),
                                        Paragraph(action.get('processus', ''), styles['TableCell']),
                                        Paragraph(action.get('description', ''), styles['TableCell']),
                                        Paragraph(action.get('responsable', ''), styles['TableCell']),
                                        Paragraph(action.get('statut', ''), styles['TableCell'])
                                    ])
                            
                            if len(actions_data) > 1:
                                actions_table = Table(actions_data, colWidths=[0.8*inch, 1.2*inch, 2.5*inch, 1.2*inch, 0.8*inch])
                                actions_table.setStyle(TableStyle([
                                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A1600FFF')),  # Vert forêt
                                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                                ]))
                                story.append(actions_table)
                        else:
                            story.append(Paragraph("Aucune action de suivi enregistrée.", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # 3. Non-conformités
                        story.append(Paragraph("3. NON-CONFORMITÉS ET ACTIONS CORRECTIVES", styles['SubTitle']))
                        
                        if journal.get('non_conformites_list') and len(journal['non_conformites_list']) > 0:
                            nc_data = [
                                [Paragraph("Date", styles['TableHeader']), 
                                 Paragraph("Description", styles['TableHeader']), 
                                 Paragraph("Cause", styles['TableHeader']), 
                                 Paragraph("Action", styles['TableHeader']), 
                                 Paragraph("Responsable", styles['TableHeader']), 
                                 Paragraph("Statut", styles['TableHeader'])]
                            ]
                            
                            for nc in journal['non_conformites_list']:
                                if isinstance(nc, dict):
                                    nc_data.append([
                                        Paragraph(nc.get('date', ''), styles['TableCell']),
                                        Paragraph(nc.get('description', ''), styles['TableCell']),
                                        Paragraph(nc.get('cause', ''), styles['TableCell']),
                                        Paragraph(nc.get('action', ''), styles['TableCell']),
                                        Paragraph(nc.get('responsable', ''), styles['TableCell']),
                                        Paragraph(nc.get('statut', ''), styles['TableCell'])
                                    ])
                            
                            if len(nc_data) > 1:
                                nc_table = Table(nc_data, colWidths=[0.7*inch, 1.5*inch, 1.2*inch, 1.5*inch, 1.0*inch, 0.7*inch])
                                nc_table.setStyle(TableStyle([
                                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A1600FFF')),  # Vert forêt
                                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                    ('FONTSIZE', (0, 0), (-1, 0), 6),
                                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                                    ('FONTSIZE', (0, 1), (-1, -1), 6),
                                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                                ]))
                                story.append(nc_table)
                        else:
                            story.append(Paragraph("Aucune non-conformité enregistrée.", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # 4. Indicateurs de performance
                        story.append(Paragraph("4. INDICATEURS DE PERFORMANCE", styles['SubTitle']))
                        
                        if journal.get('indicateurs_list') and len(journal['indicateurs_list']) > 0:
                            indicateurs_data = [
                                [Paragraph("Indicateur", styles['TableHeader']), 
                                 Paragraph("Valeur cible", styles['TableHeader']), 
                                 Paragraph("Valeur actuelle", styles['TableHeader']), 
                                 Paragraph("Analyse", styles['TableHeader'])]
                            ]
                            
                            for ind in journal['indicateurs_list']:
                                if isinstance(ind, dict):
                                    indicateurs_data.append([
                                        Paragraph(ind.get('nom', ''), styles['TableCell']),
                                        Paragraph(ind.get('cible', ''), styles['TableCell']),
                                        Paragraph(ind.get('actuel', ''), styles['TableCell']),
                                        Paragraph(ind.get('analyse', ''), styles['TableCell'])
                                    ])
                            
                            if len(indicateurs_data) > 1:
                                ind_table = Table(indicateurs_data, colWidths=[1.5*inch, 1.0*inch, 1.0*inch, 2.0*inch])
                                ind_table.setStyle(TableStyle([
                                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A1600FFF')),  # Vert forêt
                                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                    ('FONTSIZE', (0, 0), (-1, 0), 7),
                                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                                ]))
                                story.append(ind_table)
                        else:
                            story.append(Paragraph("Aucun indicateur de performance enregistré.", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # 5. Revues et Décisions
                        story.append(Paragraph("5. REVUES ET DÉCISIONS", styles['SubTitle']))
                        
                        if journal.get('revue_date') or journal.get('revue_participants') or journal.get('revue_decisions'):
                            revue_info = []
                            if journal.get('revue_date'):
                                revue_info.append(Paragraph(f"<b>Date de la revue:</b> {journal['revue_date']}", styles['Justified']))
                            if journal.get('revue_participants'):
                                revue_info.append(Paragraph(f"<b>Participants:</b> {journal['revue_participants']}", styles['Justified']))
                            if journal.get('revue_decisions'):
                                story.append(Paragraph("<b>Décisions prises:</b>", styles['Heading4']))
                                decisions = journal['revue_decisions'].split('\n') if isinstance(journal['revue_decisions'], str) else [journal['revue_decisions']]
                                for decision in decisions:
                                    if decision.strip():
                                        story.append(Paragraph(f"• {decision.strip()}", styles['Justified']))
                            
                            for info in revue_info:
                                story.append(info)
                        else:
                            story.append(Paragraph("Aucune revue ou décision enregistrée.", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # 6. Plans d'amélioration
                        story.append(Paragraph("6. PLANS D'AMÉLIORATION CONTINUE", styles['SubTitle']))
                        
                        if journal.get('plans_list') and len(journal['plans_list']) > 0:
                            plans_data = [
                                [Paragraph("Action", styles['TableHeader']), 
                                 Paragraph("Objectif", styles['TableHeader']), 
                                 Paragraph("Responsable", styles['TableHeader']), 
                                 Paragraph("Délai", styles['TableHeader'])]
                            ]
                            
                            for plan in journal['plans_list']:
                                if isinstance(plan, dict):
                                    plans_data.append([
                                        Paragraph(plan.get('action', ''), styles['TableCell']),
                                        Paragraph(plan.get('objectif', ''), styles['TableCell']),
                                        Paragraph(plan.get('responsable', ''), styles['TableCell']),
                                        Paragraph(plan.get('delai', ''), styles['TableCell'])
                                    ])
                            
                            if len(plans_data) > 1:
                                plans_table = Table(plans_data, colWidths=[2.0*inch, 2.0*inch, 1.2*inch, 0.8*inch])
                                plans_table.setStyle(TableStyle([
                                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A1600FFF')),  # Vert forêt
                                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                    ('FONTSIZE', (0, 0), (-1, 0), 7),
                                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                                ]))
                                story.append(plans_table)
                        else:
                            story.append(Paragraph("Aucun plan d'amélioration enregistré.", styles['Justified']))
                        
                        story.append(Spacer(1, 12))
                        
                        # Observations générales
                        if journal.get('observations'):
                            story.append(Paragraph("OBSERVATIONS GÉNÉRALES:", styles['SubTitle']))
                            story.append(Paragraph(journal['observations'], styles['Justified']))
                        
                        story.append(Spacer(1, 15))
                        story.append(Paragraph("-" * 80, styles['BodyText']))
                        story.append(Spacer(1, 15))
                
                story.append(Spacer(1, 15))
            
            # Saut de page après chaque champ
            story.append(PageBreak())
        
        # Générer le PDF
        pdf.build(story)
        
        # Préparer la réponse
        buffer.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"domaine_{domaine['code']}_complet_{timestamp}.pdf"
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        flash(f'Erreur lors de la génération du fichier PDF: {str(e)}', 'error')
        return redirect(url_for('gestion_domaines'))
    
    finally:
        cursor.close()
        conn.close()
# Tableau de bord
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as total FROM domaines")
    total_domaines = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM champs")
    total_champs = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM qualite_references")
    total_references = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM journaux_qualite")
    total_journaux = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', 
                         total_domaines=total_domaines,
                         total_champs=total_champs,
                         total_references=total_references,
                         total_journaux=total_journaux)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)