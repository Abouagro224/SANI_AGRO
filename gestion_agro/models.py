from django.db import models
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.contrib.auth.models import User
import uuid
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
   
    seuil_alerte = models.PositiveIntegerField(default=500) # Alerte si stock < 500kg

    
    def __str__(self):
        prod_nom = self.producteur.nom_complet if self.producteur else "Inconnu"
        return f"{self.nom} - {self.quantite_disponible} {self.get_unite_display()} ({prod_nom})"

    def save(self, *args, **kwargs):
        # Initialisation du stock lors de la première création
        if not self.pk: 
            self.quantite_disponible = self.quantite_initiale
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

    def __str__(self):
        return f"Livraison {self.id} ({self.statut})"

class Notification(models.Model):
    destinataire = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)
    lu = models.BooleanField(default=False)

    def _str_(self):
        return f"Notif pour {self.destinataire.username}"
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

