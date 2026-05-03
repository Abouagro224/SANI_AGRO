from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from gestion_agro import views


urlpatterns = [
    # --- ADMINISTRATION ---
    path('admin/', admin.site.urls),
    path('tableau-de-bord-admin/', views.dashboard_admin_stats, name='dashboard_admin'),
    
    # --- ACCUEIL & DIRECTION ---
    path('', views.catalogue_produits, name='catalogue_produits'),
    path('aiguillage/', views.direction_vue, name='direction_vue'),
    
    # --- DASHBOARDS (ESPACES PERSONNELS) ---
    path('dashboard/producteur/', views.dashboard_producteur, name='dashboard_producteur'),
    path('dashboard/commercant/', views.dashboard_commercant, name='dashboard_commercant'),
    path('dashboard/transporteur/', views.dashboard_transporteur, name='dashboard_transporteur'),
    
    # --- GESTION DES PRODUITS (PRODUCTEUR) ---
    path('produit/ajouter/', views.ajouter_produit, name='publier_produit'),
    path('produit/modifier/<int:produit_id>/', views.modifier_produit, name='modifier_produit'),
    path('produit/supprimer/<int:produit_id>/', views.supprimer_produit, name='supprimer_produit'),
    path('modifier-photo/', views.modifier_photo_profil, name='modifier_photo_profil'),
    
    # --- RÉSERVATIONS & PAIEMENTS (COMMERÇANT) ---
    path('reserver/<int:produit_id>/', views.reserver_produit, name='reserver_produit'),
    path('caution/payer/<int:reservation_id>/', views.valider_paiement_caution, name='valider_paiement_caution'),
    path('caution/valider/<int:reservation_id>/', views.valider_la_caution, name='valider_la_caution'),
    
    # --- LOGISTIQUE & TRANSPORT (TRANSPORTEUR) ---
    # 1. Pour prendre la route (Création de la livraison)
    path('accepter-mission/<int:reservation_id>/', views.accepter_mission, name='accepter_mission'),
    
    # 2. IMPORTANT : Pour confirmer l'arrivée (Clôture de la mission)
    path('terminer-livraison/<int:livraison_id>/', views.terminer_livraison, name='terminer_livraison'),
    path('confirmer-reception/<int:livraison_id>/', views.confirmer_reception, name='confirmer_reception'),
    path('suivre-livraison/<int:livraison_id>/', views.suivre_livraison, name='suivre_livraison'),
     path('recu/<int:reservation_id>/', views.generer_recu, name='generer_recu'),
]


# Gestion des fichiers médias
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)