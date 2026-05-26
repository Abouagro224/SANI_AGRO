from django.db import models
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.contrib.auth.models import User
import uuid
from django.dispatch import receiver
from django.db.models.signals import post_save
from datetime import  timedelta
from django.utils import timezone
# --- CONSTANTES ---
LISTE_MARCHES = [
    ('MEDINE', 'Marché de Médine'),
    ('NIARÉLA', 'Marché de Niaréla'),
    ('DIBIDA', 'Marché de Dibida'),
    ('COURS_FLEUVE', 'Marché du Cours fleuve'),
    ('BOUGOBA', 'Marché de Bougoba'),
]

ZONES_CHOICES =[
    ('SIKASSO','Sikasso'),
    ('BAGUINEDA', 'Baguineda'),
    ('SEGOU','Segou')
]

# --- MODÈLES ---

class Producteur(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='producteur_profil', null=True, blank=True)
    nom_complet = models.CharField(max_length=255)
    village = models.CharField(max_length=255)
    telephone = models.CharField(max_length=20)
    photo_profil = models.ImageField(upload_to='profils/', null=True, blank=True)
    est_verifie = models.BooleanField(default=False)
    score_confiance = models.IntegerField(default=100) # Score sur 100


    def __str__(self):
        return self.nom_complet

class ProduitAgricole(models.Model):
    UNITES =[
        ('KG','Kilogramme'),
        ('TONNE', 'Tonne'),
        ('SAC','Sac'),
    ]

    # --- Nouveaux choix pour la vente avant récolte ---
    STATUT_RECOLTE = [
        ('SUR_PIED', '🌳 En cours de maturité (Sur pied)'),
        ('RECOLTE', '📦 Récolté et prêt'),
    ]
    # --- DICTIONNAIRE DE CONSERVATION AUTOMATIQUE (en jours) ---
    DUREE_CONSERVATION = {
        'TOMATE': 10,
        'MANGUE': 21,
        'OIGNON': 90,
        'POMME DE TERRE': 60,
        'POMME_DE_TERRE': 60,
        'MAÏS': 180,
        'MAIS': 180,
        'RIZ': 365,
    }
    producteur = models.ForeignKey(Producteur, on_delete=models.CASCADE, null=True, blank=True, related_name='produits')
    nom = models.CharField(max_length=100)
    
    # On garde quantite_initiale comme la prévision faite par le producteur
    quantite_initiale = models.PositiveBigIntegerField(default=0, verbose_name="Quantité totale prévue")
    quantite_disponible = models.PositiveBigIntegerField(default=0, verbose_name="Reste disponible")
    
    unite = models.CharField(max_length=10, choices=UNITES, default='KG')
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='produits/')
    video_demonstration = models.FileField(upload_to='videos_produits/', null=True, blank=True)
    
    # --- Champs pour la planification ---
    statut_recolte = models.CharField(max_length=20, choices=STATUT_RECOLTE, default='SUR_PIED')
    date_recolte_prevue = models.DateField(null=True, blank=True, verbose_name="Date de récolte prévue")
    
    zone_production = models.CharField(max_length=50, choices=ZONES_CHOICES, default='SIKASSO')
    zone_origine = models.CharField(max_length=100) # Ex: "Cercle de Yanfolila"
    
    est_promotion = models.BooleanField(default=False)
    date_publication = models.DateTimeField(auto_now_add=True)
    date_peremption_prevue = models.DateField(null=True, blank=True, verbose_name="Date limite de conservation au champ")
    
   
    seuil_alerte = models.PositiveIntegerField(default=500) # Alerte si stock < 500kg
    @property
    def statut_alerte(self):
        """Détecte l'urgence : PERIME, URGENT ou OK."""
        if not self.date_peremption_prevue: 
            return "NON_DEFINI"
        
        # Calcul des jours restants
        jours_restants = (self.date_peremption_prevue - timezone.now().date()).days
        
        if jours_restants < 0: 
            return "PERIME"
        if jours_restants <= 3: 
            return "URGENT"
        return "OK"

    
    @property
    def prix_conseille(self):
        """Propose une remise de 20% sécurisée."""
        if self.statut_alerte == "URGENT":
            # On utilise Decimal('0.80') au lieu de 0.80
            return round(self.prix_unitaire * Decimal('0.80'), 0)
        return self.prix_unitaire


    
    def save(self, *args, **kwargs):
        # 1. Initialisation du stock lors de la première création
        if not self.pk: 
            self.quantite_disponible = self.quantite_initiale
            
        # 2. CALCUL AUTOMATIQUE DE LA DATE DE PÉREMPTION
        if not self.date_peremption_prevue:
            # On récupère la date de récolte ou la date du jour
            raw_date = self.date_recolte_prevue if self.date_recolte_prevue else timezone.now()
            
            # SÉCURITÉ : On transforme systématiquement en objet 'date' pur
            # Cela élimine le risque d'avoir un datetime avec des heures/minutes
            if hasattr(raw_date, 'date'):
                date_depart = raw_date.date()
            else:
                date_depart = raw_date
            
            # Nettoyage du nom pour correspondre à ton dictionnaire
            nom_nettoye = self.nom.strip().upper()
            
            # Récupération de la durée avec valeur par défaut 14
            jours = int(self.DUREE_CONSERVATION.get(nom_nettoye, 14))
            
            # Calcul : Addition de deux objets 'date' et 'timedelta'
            self.date_peremption_prevue = date_depart + timedelta(days=jours)
            
            
        # Appel final à la méthode save parente
        super().save(*args, **kwargs)
class Commercant(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='commercant_profil', null=True, blank=True)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20)
    ville_marche = models.CharField(max_length=100)
    

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.ville_marche})"

class Transporteur(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='transporteur_profil', null=True, blank=True)
    nom = models.CharField(max_length=100, verbose_name="Nom du Transporteur/Compagnie")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    vehicule = models.CharField(max_length=50, verbose_name="Type de véhicule (ex: Camion 10t)")
    photo_profil = models.ImageField(upload_to='profils_transports/', null=True, blank=True)
    plaque_immatriculation = models.CharField(max_length=20, verbose_name="N° Plaque")
    disponible = models.BooleanField(default=True, verbose_name="Disponible")
    tarif_base = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Tarif de base (FCFA)")

    def __str__(self):
        return f"{self.nom} - {self.vehicule}"
class Reservation(models.Model):
    CHOIX_PAIEMENT = [('OM', 'Orange Money'), ('MOOV', 'Moov Money'), ('CASH', 'Espèces/Dépôt')]
    
    produit = models.ForeignKey(ProduitAgricole, on_delete=models.CASCADE)
    commercant = models.ForeignKey(Commercant, on_delete=models.CASCADE)
    quantite_voulue = models.PositiveIntegerField(default=0)
    date_reservation = models.DateTimeField(auto_now_add=True)
    # Assure-toi que LISTE_MARCHES est défini au-dessus de cette classe
    marche_destination = models.CharField(max_length=50, choices=LISTE_MARCHES, default='MEDINE')
    mode_paiement = models.CharField(max_length=20, choices=CHOIX_PAIEMENT, default='CASH')
    ref_transaction = models.CharField(max_length=100, null=True, blank=True)
    statut_caution = models.CharField(
        max_length=20,
        choices=[('NON_PAYE', '❌ En attente'), ('PAYE', '✅ Payée')],
        default='NON_PAYE'
    )
    date_disponibilite = models.DateField(null=True, blank=True)
    confirmation_producteur = models.BooleanField(default=False)
    prix_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    caution_20 = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)

    def save(self, *args, **kwargs):
        # 1. Calcul des prix (Conversion en Decimal pour éviter les erreurs de calcul)
        self.prix_total = Decimal(self.produit.prix_unitaire) * Decimal(self.quantite_voulue)
        # On calcule les 20% de caution
        self.caution_20 = (self.prix_total * Decimal('0.20')).quantize(Decimal('0.01'))
        
        # 2. Gestion du stock
        if not self.pk: # Seulement à la création
            if self.produit.quantite_disponible >= self.quantite_voulue:
                self.produit.quantite_disponible -= self.quantite_voulue
                self.produit.save()
            else:
                # Optionnel : lever une erreur si le stock est insuffisant
                raise ValidationError("Stock insuffisant pour cette réservation")
            
        super().save(*args, **kwargs)  
    @property
    def reste_a_payer(self):
        # Cette fonction calcule le montant que le commerçant doit encore au producteur
        return self.prix_total - self.caution_20

    @property
    def nom_du_producteur(self):
        # Pour afficher facilement le nom du producteur dans tes tableaux
        return self.produit.producteur.nom_complet if self.produit.producteur else "Inconnu"      



class Livraison(models.Model):
    STATUT_CHOICES = [
        ('en_attente', '⏳ En attente'),
        ('en_route', '🚛 En route'),
        ('livre', '✅ Livré'),
    ]
    reservation = models.OneToOneField(Reservation, on_delete=models.CASCADE)
    transporteur = models.ForeignKey(Transporteur, on_delete=models.SET_NULL, null=True, blank=True)
    date_depart = models.DateTimeField(null=True, blank=True)
    date_arrivee_estimee = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    frais_transport = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_depart = models.DateTimeField(null=True, blank=True, verbose_name="Départ prévu du dépôt")
    date_chargement_reel = models.DateTimeField(null=True, blank=True, verbose_name="Chargement effectif au champ") 
    date_arrivee_estimee = models.DateTimeField(null=True, blank=True, verbose_name="Arrivée estimée à destination")
    date_livraison_reelle = models.DateTimeField(null=True, blank=True, verbose_name="Livraison effective au commerçant") 

    def __str__(self):
        return f"Livraison {self.id} ({self.statut})"

class Notification(models.Model):
    TYPES = [('INFO', 'Info'), ('COMMANDE', 'Commande'), ('ALERTE', 'Alerte')]
    destinataire = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications_systeme')
    titre = models.CharField(max_length=100, default="Nouvelle notification")
    message = models.TextField()
    type_notif = models.CharField(max_length=20, choices=TYPES, default='INFO')
    date_creation = models.DateTimeField(auto_now_add=True)
    lu = models.BooleanField(default=False)

    def _str_(self):
        return f"{self.titre} pour {self.destinataire.username}"

# --- L'AUTOMATISME (SIGNALS) ---

# --- L'AUTOMATISME (SIGNALS) ---

@receiver(post_save, sender=Reservation)
def gerer_notifications_reservation(sender, instance, created, **kwargs):
    """Gère toutes les notifications liées au cycle de vie d'une réservation"""
    try:
        if created:
            # 1. NOTIFIER LE PRODUCTEUR (Nouvelle réservation)
            user_prod = instance.produit.producteur.user
            if user_prod:
                Notification.objects.create(
                    destinataire=user_prod,
                    titre="📦 Nouvelle Réservation",
                    message=f"Le commerçant {instance.commercant.prenom} a réservé : {instance.produit.nom}.",
                    type_notif='COMMANDE'
                )
        else:
            # 2. NOTIFIER LE COMMERÇANT (Si le producteur confirme)
            # On utilise ton champ 'confirmation_producteur'
            if instance.confirmation_producteur:
                Notification.objects.get_or_create(
                    destinataire=instance.commercant.user,
                    titre="✅ Réservation Confirmée",
                    message=f"Votre réservation pour {instance.produit.nom} a été validée par le producteur.",
                    type_notif='INFO'
                )
    except Exception as e:
        print(f"Erreur notification Reservation : {e}")

@receiver(post_save, sender=Livraison)
def notifier_transporteur_et_commercant(sender, instance, created, **kwargs):
    """Notifie le transporteur d'une mission et le commerçant du départ"""
    try:
        if created and instance.transporteur:
            # 1. NOTIFIER LE TRANSPORTEUR (Nouvelle mission)
            Notification.objects.create(
                destinataire=instance.transporteur.user,
                titre="🚛 Nouvelle Mission",
                message=f"Vous avez une mission pour transporter {instance.reservation.produit.nom}.",
                type_notif='INFO'
            )
        
        # 2. NOTIFIER LE COMMERÇANT (Si le statut change en 'en_route')
        if instance.statut == 'en_route':
            Notification.objects.get_or_create(
                destinataire=instance.reservation.commercant.user,
                titre="🚚 Marchandise en route",
                message=f"Votre commande de {instance.reservation.produit.nom} est en cours de livraison.",
                type_notif='INFO'
            )
    except Exception as e:
        print(f"Erreur notification Livraison : {e}")
class Avis(models.Model):
    producteur = models.ForeignKey(Producteur, on_delete=models.CASCADE, related_name='avis')
    commercant = models.ForeignKey(User, on_delete=models.CASCADE) # ou ton modèle Commerçant
    commentaire = models.TextField()
    note = models.IntegerField(default=5)
    date_publication = models.DateTimeField(auto_now_add=True)   
class FluxProduit(models.Model):
    livraison = models.ForeignKey('Livraison', on_delete=models.CASCADE, related_name='etapes')
    etape = models.CharField(max_length=100, verbose_name="Action effectuée")
    localisation = models.CharField(max_length=255, verbose_name="Lieu actuel")
    date_heure = models.DateTimeField(auto_now_add=True)
    code_tracabilite = models.CharField(max_length=50, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.code_tracabilite:
            # Génère un code unique pour le suivi logistique
            self.code_tracabilite = f"ML-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.etape} - {self.localisation}"

class Litige(models.Model):
    livraison = models.ForeignKey('Livraison', on_delete=models.CASCADE, related_name='litiges')
    declarant = models.ForeignKey(User, on_delete=models.CASCADE)
    motif = models.TextField(verbose_name="Description du problème")
    date_creation = models.DateTimeField(auto_now_add=True)
    resolu = models.BooleanField(default=False, verbose_name="Est résolu ?")

    def __str__(self):
        return f"Litige #{self.id} sur Livraison {self.livraison.id}"    

