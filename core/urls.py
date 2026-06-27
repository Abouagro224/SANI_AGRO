from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from gestion_agro import views
from django.contrib.auth import views as auth_views 



urlpatterns = [
    # --- 1. LA PAGE D'ACCUEIL (PRIORITÉ) ---
    path('', views.accueil, name='accueil'),

    # --- 2. LE CATALOGUE ---
    path('catalogue/', views.catalogue_produits, name='catalogue_produits'),

    # --- ADMINISTRATION ---
    path('admin/', admin.site.urls),
    
    
    # --- DIRECTION ---
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
    path('reservation/annuler/<int:reservation_id>/', views.annuler_reservation, name='annuler_reservation'),
    path('caution/payer/<int:reservation_id>/', views.valider_paiement_caution, name='valider_paiement_caution'),
    path('caution/valider/<int:reservation_id>/', views.valider_la_caution, name='valider_la_caution'),
    
    # --- LOGISTIQUE & TRANSPORT (TRANSPORTEUR) ---
    path('accepter-mission/<int:reservation_id>/', views.accepter_mission, name='accepter_mission'),
    path('charger-marchandise/<int:livraison_id>/', views.charger_marchandise, name='charger_marchandise'), # 👈 ROUTE AJOUTÉE POUR LE CHARGEMENT AU CHAMP
    path('terminer-livraison/<int:livraison_id>/', views.terminer_livraison, name='terminer_livraison'),
    path('confirmer-reception/<int:livraison_id>/', views.confirmer_reception, name='confirmer_reception'),
    path('declarer-litige/<int:livraison_id>/', views.declarer_litige, name='declarer_litige'),
    path('suivre-livraison/<int:livraison_id>/', views.suivre_livraison, name='suivre_livraison'),
    path('recu/<int:reservation_id>/', views.generer_recu, name='generer_recu'),
    
    # --- AUTHENTIFICATION & INSCRIPTION ---
    path('inscription/', views.inscription_choix, name='inscription_choix'),
    path('inscription/<str:role>/', views.inscription_final, name='inscription_final'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    
    # LIGNE POUR RÉPARER L'ERREUR JAUNE :
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # --- AIGUILLAGE INTELLIGENT (ACCUEIL) ---
    path('acces-vendre/', views.clic_vendre, name='clic_vendre'),
    path('acces-marche/', views.clic_marche, name='clic_marche'),
    path('acces-transport/', views.clic_transport, name='clic_transport'),
    path('produit/marquer-recolte/<int:produit_id>/', views.marquer_recolte, name='marquer_recolte'),
    path('reservation/changer-statut-livraison/<int:reservation_id>/', views.changer_statut_livraison, name='changer_statut_livraison'),
    path('publier-demande/', views.publier_demande_marche, name='publier_demande_marche'),
    path('demandes-marche/', views.demandes_marche_producteur, name='demandes_marche_producteur'),
    path('s-engager-demande/<int:demande_id>/', views.s_engager_demande, name='s_engager_demande'),
    path('satisfaire-demande/<int:demande_id>/', views.satisfaire_demande, name='satisfaire_demande'),
    path('choisir-transporteur/<int:reservation_id>/', views.choisir_transporteur, name='choisir_transporteur'),
    path('attribuer-transporteur/<int:reservation_id>/', views.attribuer_transporteur, name='attribuer_transporteur'),
    path('gestionnaire/valider-cautions/', views.valider_caution_admin, name='valider_caution_admin'),
    path('declarer-reste-paye/<int:reservation_id>/', views.declarer_reste_paye, name='declarer_reste_paye'),
    path('confirmer-reste-paye/<int:reservation_id>/', views.confirmer_reste_paye, name='confirmer_reste_paye'), 
    path('verifier-identite/', views.verifier_identite, name='verifier_identite'),
    path('accepter-proposition/<int:livraison_id>/', views.accepter_proposition, name='accepter_proposition'),
    path('refuser-proposition/<int:livraison_id>/', views.refuser_proposition, name='refuser_proposition'),
    path('tableau-de-bord-admin/', views.dashboard_admin_stats, name='dashboard_admin_stats'),
    path('verifier-identite-admin/<str:type_profil>/<int:profil_id>/', views.verifier_identite_admin, name='verifier_identite_admin'),
    path('rejeter-identite-admin/<str:type_profil>/<int:profil_id>/', views.rejeter_identite_admin, name='rejeter_identite_admin'),
    path('gestion/bloquer/<str:type_profil>/<int:profil_id>/', views.bloquer_utilisateur, name='bloquer_utilisateur'),
    path('gestion/debloquer/<str:type_profil>/<int:profil_id>/', views.debloquer_utilisateur, name='debloquer_utilisateur'),
    path('gestion/resoudre-litige/<int:litige_id>/', views.resoudre_litige, name='resoudre_litige'),
    path('produit/retirer/<int:produit_id>/', views.retirer_produit, name='retirer_produit'),
    path('reservation/modifier/<int:reservation_id>/', views.modifier_reservation, name='modifier_reservation'),
    path('calendrier/', views.calendrier, name='calendrier'),
    path('gestion/transactions/', views.dashboard_transactions_admin, name='dashboard_transactions_admin'),
    path('gestion/transactions/effectuer/<int:transaction_id>/', views.marquer_transaction_effectue, name='marquer_transaction_effectue'),
    path('recu-transaction/<int:transaction_id>/', views.telecharger_recu_transaction, name='telecharger_recu_transaction'),
    path('bon-livraison/<int:livraison_id>/', views.telecharger_bon_livraison, name='telecharger_bon_livraison'),
    path('marquer-notifications-lues/', views.marquer_notifications_lues, name='marquer_notifications_lues' ),
    path('accepter-lot/', views.accepter_lot, name='accepter_lot'),

]

# Gestion des fichiers médias
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)