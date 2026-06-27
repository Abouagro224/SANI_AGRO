from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum,F,Avg
from decimal import Decimal
import uuid 
import math
from django.db import IntegrityError
from django.utils import timezone
from datetime import datetime
from django.http import HttpResponseForbidden
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import ProduitAgricole, Producteur,Transaction, Reservation, Commercant, Livraison, Transporteur, FluxProduit, Litige, AlerteSecuriteRoutiere, DemandeMarche,Notification,ZoneProduction,Marche
from datetime import date
from django.contrib.admin.views.decorators import staff_member_required
def render_to_pdf(template_src, context_dict):
    template = get_template(template_src)
    html = template.render(context_dict)
    response = HttpResponse(content_type='application/pdf')
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Erreur PDF', status=500)
    return response
@login_required
def calendrier(request):
    # Identifier le profil de l'utilisateur
    profil = None
    evenements = []

    if hasattr(request.user, 'producteur_profil'):
        profil = request.user.producteur_profil

        # Récupérer les dates de récolte de ses propres produits
        produits = ProduitAgricole.objects.filter(producteur=profil, date_recolte_prevue__isnull=False)
        for p in produits:
            evenements.append({
                'title': f'Récolte : {p.nom}',
                'start': p.date_recolte_prevue.isoformat(),
                'color': '#2e7d32',  # Vert
                'extendedProps': {'type': 'recolte'}
            })
            if p.date_peremption_prevue:
                evenements.append({
                    'title': f'Limite : {p.nom}',
                    'start': p.date_peremption_prevue.isoformat(),
                    'color': '#d32f2f',  # Rouge
                    'extendedProps': {'type': 'peremption'}
                })

        # Réservations faites par les commerçants sur ses produits
        reservations = Reservation.objects.filter(produit__producteur=profil, date_disponibilite__isnull=False)
        for r in reservations:
            evenements.append({
                'title': f'Réservation : {r.commercant.nom} - {r.produit.nom} ({r.quantite_voulue} kg)',
                'start': r.date_disponibilite.isoformat(),
                'color': '#7b1fa2',  # Violet
                'extendedProps': {'type': 'reservation'}
            })

    elif hasattr(request.user, 'commercant_profil'):
        profil = request.user.commercant_profil

        # Ses propres réservations
        reservations = Reservation.objects.filter(commercant=profil, date_disponibilite__isnull=False)
        for r in reservations:
            evenements.append({
                'title': f'Réservation : {r.produit.nom} ({r.quantite_voulue} kg)',
                'start': r.date_disponibilite.isoformat(),
                'color': '#7b1fa2',
                'extendedProps': {'type': 'reservation'}
            })

        # Ses demandes de marché
        demandes = DemandeMarche.objects.filter(commercant=profil, date_besoin__isnull=False)
        for d in demandes:
            evenements.append({
                'title': f'Besoin : {d.produit} ({d.quantite} kg)',
                'start': d.date_besoin.isoformat(),
                'color': '#1565c0',  # Bleu
                'extendedProps': {'type': 'demande'}
            })

        # Livraisons liées à ses achats
        livraisons = Livraison.objects.filter(reservation__commercant=profil, date_arrivee_estimee__isnull=False)
        for l in livraisons:
            evenements.append({
                'title': f'Livraison : {l.reservation.produit.nom}',
                'start': l.date_arrivee_estimee.isoformat(),
                'color': '#e65100',  # Orange
                'extendedProps': {'type': 'livraison'}
            })

    elif hasattr(request.user, 'transporteur_profil'):
        profil = request.user.transporteur_profil

        # Livraisons qu'il doit assurer
        livraisons = Livraison.objects.filter(transporteur=profil, date_arrivee_estimee__isnull=False)
        for l in livraisons:
            evenements.append({
                'title': f'Livraison : {l.reservation.produit.nom}',
                'start': l.date_arrivee_estimee.isoformat(),
                'color': '#e65100',
                'extendedProps': {'type': 'livraison'}
            })

    context = {
        'evenements': evenements,
    }
    return render(request, 'gestion_agro/calendrier.html', context)
@login_required
def annuler_reservation(request, reservation_id):
    # Vérifier que l'utilisateur est bien un commerçant
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent annuler une réservation.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, commercant=request.user.commercant_profil)

    # Annulation autorisée uniquement si la caution n'est ni BLOQUEE ni PAYE
    if reservation.statut_caution not in ['NON_PAYE', 'ATTENTE_VALIDATION']:
        messages.error(request, "Vous ne pouvez plus annuler cette réservation (caution déjà bloquée ou validée).")
        return redirect('dashboard_commercant')

    # Sauvegarder les infos avant suppression pour le message
    produit = reservation.produit
    qte = reservation.quantite_voulue
    caution = reservation.caution_20
    statut = reservation.statut_caution

    # Remettre le stock
    produit.quantite_disponible += qte
    produit.save()

    # ✅ AJOUTER LA TRANSACTION DE REMBOURSEMENT SI LA CAUTION ÉTAIT EN ATTENTE
    if statut == 'ATTENTE_VALIDATION':
        Transaction.objects.create(
            reservation=reservation,
            type_transaction='REMBOURSEMENT',
            montant=caution,
            commentaire=f"Remboursement suite à l'annulation de la réservation #{reservation.id}"
        )

    # Supprimer la réservation
    reservation.delete()

    # Message adapté selon le statut
    if statut == 'ATTENTE_VALIDATION':
        messages.success(request, f"✅ Réservation annulée. Les {qte} kg ont été remis en stock. Une demande de remboursement de {caution} FCFA a été transmise à l'administrateur.")
    else:
        messages.success(request, f"✅ Réservation annulée. Les {qte} kg ont été remis en stock.")

    return redirect('dashboard_commercant')
@login_required
def retirer_produit(request, produit_id):
    # Vérifier que l'utilisateur est bien un producteur
    if not hasattr(request.user, 'producteur_profil'):
        messages.error(request, "Seuls les producteurs peuvent retirer un produit.")
        return redirect('direction_vue')

    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur=request.user.producteur_profil)

    if produit.quantite_disponible == 0:
        messages.warning(request, "Ce produit a déjà une quantité disponible nulle.")
    else:
        produit.quantite_disponible = 0
        produit.save()
        messages.success(request, f"Le produit '{produit.nom}' a été retiré du catalogue.")

    return redirect('dashboard_producteur')
@login_required
def modifier_reservation(request, reservation_id):
    # Vérifier que l'utilisateur est bien un commerçant
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent modifier une réservation.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, commercant=request.user.commercant_profil)

    # Modifications autorisées seulement si NON_PAYE ou ATTENTE_VALIDATION
    if reservation.statut_caution not in ['NON_PAYE', 'ATTENTE_VALIDATION']:
        messages.error(request, "Vous ne pouvez plus modifier cette réservation (caution déjà bloquée ou payée).")
        return redirect('dashboard_commercant')

    if request.method == 'POST':
        nouvelle_quantite = int(request.POST.get('quantite_voulue', 0))

        if nouvelle_quantite <= 0:
            messages.error(request, "La quantité doit être supérieure à zéro.")
            return redirect('dashboard_commercant')

        produit = reservation.produit
        ancienne_quantite = reservation.quantite_voulue

        # Vérifier si le stock permet cette modification
        stock_disponible = produit.quantite_disponible + ancienne_quantite  # on remet d'abord l'ancienne quantité
        if nouvelle_quantite > stock_disponible:
            messages.error(request, f"Stock insuffisant. Actuellement disponible (avec votre réservation) : {stock_disponible} kg.")
            return redirect('dashboard_commercant')

        # Mettre à jour le stock
        produit.quantite_disponible = stock_disponible - nouvelle_quantite
        produit.save()

        # Mettre à jour la réservation
        reservation.quantite_voulue = nouvelle_quantite
        reservation.prix_total = Decimal(produit.prix_unitaire) * Decimal(nouvelle_quantite)
        reservation.caution_20 = (reservation.prix_total * Decimal('0.20')).quantize(Decimal('0.01'))
        reservation.save()

        messages.success(request, f"Réservation mise à jour : {nouvelle_quantite} kg. Nouvelle caution : {reservation.caution_20} FCFA.")
        return redirect('dashboard_commercant')

    # GET : afficher un petit formulaire
    return render(request, 'gestion_agro/modifier_reservation.html', {'reservation': reservation})
@login_required
def resoudre_litige(request, litige_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    litige = get_object_or_404(Litige, id=litige_id)
    litige.resolu = True
    litige.save()
    messages.success(request, f"Litige #{litige.id} marqué comme résolu.")
    return redirect('dashboard_admin_stats')

@login_required
def verifier_identite(request):
    user = request.user
    if hasattr(user, 'producteur_profil'):
        profil = user.producteur_profil
        dashboard_url = 'dashboard_producteur'
    elif hasattr(user, 'commercant_profil'):
        profil = user.commercant_profil
        dashboard_url = 'dashboard_commercant'
    elif hasattr(user, 'transporteur_profil'):
        profil = user.transporteur_profil
        dashboard_url = 'dashboard_transporteur'
    else:
        return redirect('direction_vue')

    if request.method == "POST":
        profil.type_piece = request.POST.get('type_piece', 'CARTE_IDENTITE')
        profil.numero_piece = request.POST.get('numero_piece', '')
        piece = request.FILES.get('piece_identite')
        if piece:
            profil.piece_identite = piece
        profil.save()
        messages.success(request, "Pièce d'identité envoyée. L'admin va vérifier votre compte.")
        return redirect(dashboard_url)

    return render(request, 'gestion_agro/verifier_identite.html', {'profil': profil})
@login_required
def verifier_identite_admin(request, type_profil, profil_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    if type_profil == 'producteur':
        profil = get_object_or_404(Producteur, id=profil_id)
    elif type_profil == 'commercant':
        profil = get_object_or_404(Commercant, id=profil_id)
    elif type_profil == 'transporteur':
        profil = get_object_or_404(Transporteur, id=profil_id)
    else:
        return redirect('dashboard_admin_stats')
    
    profil.est_verifie = True
    profil.save()
    messages.success(request, f"Identité de {profil} vérifiée avec succès.")
    return redirect('dashboard_admin_stats')


@login_required
def rejeter_identite_admin(request, type_profil, profil_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    if type_profil == 'producteur':
        profil = get_object_or_404(Producteur, id=profil_id)
    elif type_profil == 'commercant':
        profil = get_object_or_404(Commercant, id=profil_id)
    elif type_profil == 'transporteur':
        profil = get_object_or_404(Transporteur, id=profil_id)
    else:
        return redirect('dashboard_admin_stats')
    
    profil.piece_identite = None
    profil.numero_piece = ''
    profil.save()
    messages.warning(request, f"Identité de {profil} rejetée. L'utilisateur devra renvoyer sa pièce.")
    return redirect('dashboard_admin_stats')
@login_required
def declarer_reste_paye(request, reservation_id):
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent effectuer cette action.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, commercant=request.user.commercant_profil)

    if reservation.statut_reste != 'NON_PAYE':
        messages.warning(request, "Le reste a déjà été déclaré ou confirmé.")
        return redirect('dashboard_commercant')

    reservation.statut_reste = 'DECLARE'
    reservation.save()
    messages.success(request, "Vous avez déclaré avoir payé le reste. Le producteur doit maintenant confirmer.")
    return redirect('dashboard_commercant')
@login_required
def confirmer_reste_paye(request, reservation_id):
    if not hasattr(request.user, 'producteur_profil'):
        messages.error(request, "Seuls les producteurs peuvent effectuer cette action.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, produit__producteur=request.user.producteur_profil)

    if reservation.statut_reste != 'DECLARE':
        messages.warning(request, "Le commerçant n'a pas encore déclaré avoir payé le reste.")
        return redirect('dashboard_producteur')

    # Passer le reste en confirmé
    reservation.statut_reste = 'CONFIRME'
    reservation.save()

    # ✅ Créer la transaction de paiement pour le producteur (une seule fois)
    if reservation.statut_caution == 'PAYE':
        Transaction.objects.get_or_create(
            reservation=reservation,
            type_transaction='Paiement',
            defaults={
                'montant': reservation.caution_20,
                'commentaire': f"Versement de la caution au producteur {request.user.producteur_profil.nom_complet}"
            }
        )

    messages.success(request, "Reste confirmé. L'administrateur va procéder au versement de la caution.")
    return redirect('dashboard_producteur')
@staff_member_required
def valider_caution_admin(request):
    reservations_attente = Reservation.objects.filter(statut_caution='ATTENTE_VALIDATION').order_by('-date_reservation')

    if request.method == "POST":
        reservation_id = request.POST.get('reservation_id')
        action = request.POST.get('action')
        reservation = get_object_or_404(Reservation, id=reservation_id)
        if action == 'valider':
            reservation.statut_caution = 'BLOQUEE'
            reservation.save()
            messages.success(request, f"Caution de {reservation.commercant.user.username} validée et bloquée.")
        elif action == 'rejeter':
            reservation.statut_caution = 'NON_PAYE'
            reservation.preuve_paiement = None
            reservation.save()
            messages.warning(request, f"Caution de {reservation.commercant.user.username} rejetée.")
        return redirect('valider_caution_admin')

    context = {'reservations': reservations_attente}
    return render(request, 'gestion_agro/valider_caution_admin.html', context)

def expirer_demandes_depassees():
    DemandeMarche.objects.filter(statut='OUVERTE', date_besoin__lt=date.today()).update(statut='EXPIREE')

@login_required
def s_engager_demande(request, demande_id):
    if not hasattr(request.user, 'producteur_profil'):
        messages.error(request, "Seuls les producteurs peuvent s'engager sur une demande.")
        return redirect('direction_vue')
    if not request.user.producteur_profil.est_verifie:
        messages.error(request, "Votre compte doit être vérifié pour publier un produit.")
        return redirect('verifier_identite')

    demande = get_object_or_404(DemandeMarche, id=demande_id)

    if demande.statut != 'OUVERTE':
        messages.error(request, "Cette demande n'est plus disponible.")
        return redirect('catalogue_produits')

    demande.producteur_engage = request.user.producteur_profil
    demande.statut = 'ATTRIBUEE'
    demande.save()

    # Message pour le producteur
    messages.success(request, f"Vous êtes maintenant engagé pour la demande de {demande.produit}.")

    # Notification pour le commerçant (visible à sa prochaine connexion)
    messages.success(request, f"Votre demande de {demande.quantite} kg de {demande.produit} a été prise en charge par un producteur.", extra_tags='commercant_notif')

    return redirect('dashboard_producteur')
@login_required
def satisfaire_demande(request, demande_id):
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent clôturer une demande.")
        return redirect('direction_vue')

    demande = get_object_or_404(DemandeMarche, id=demande_id, commercant=request.user.commercant_profil)

    if demande.statut == 'ATTRIBUEE':
        demande.statut = 'SATISFAITE'
        demande.save()
        messages.success(request, f"Votre demande de {demande.produit} a été marquée comme satisfaite.")
    else:
        messages.error(request, "Cette demande ne peut pas être marquée comme satisfaite (elle doit d'abord être attribuée).")

    return redirect('dashboard_commercant')
@login_required
def demandes_marche_producteur(request):
    if not hasattr(request.user, 'producteur_profil'):
        messages.error(request, "Accès réservé aux producteurs.")
        return redirect('direction_vue')

    demandes = DemandeMarche.objects.filter(statut='OUVERTE').order_by('-date_publication')
    return render(request, 'gestion_agro/demandes_marche.html', {'demandes': demandes})
def enregistrer_etape_logistique(livraison, action, lieu):
    FluxProduit.objects.create(
        livraison=livraison,
        etape=action,
        localisation=lieu
    )

@login_required
def direction_vue(request):
    if Producteur.objects.filter(user=request.user).exists():
        producteur = Producteur.objects.get(user=request.user)  # ← AJOUTE
        if not producteur.est_actif:                              # ← AJOUTE
            messages.error(request, "⛔ Compte bloqué.")          # ← AJOUTE
            return redirect('login')                              # ← AJOUTE
        return redirect('dashboard_producteur')
    elif Commercant.objects.filter(user=request.user).exists():
        commercant = Commercant.objects.get(user=request.user)    # ← AJOUTE
        if not commercant.est_actif:                               # ← AJOUTE
            messages.error(request, "⛔ Compte bloqué.")           # ← AJOUTE
            return redirect('login')                               # ← AJOUTE
        return redirect('catalogue_produits')
    elif Transporteur.objects.filter(user=request.user).exists():
        transporteur = Transporteur.objects.get(user=request.user) # ← AJOUTE
        if not transporteur.est_actif:                              # ← AJOUTE
            messages.error(request, "⛔ Compte bloqué.")            # ← AJOUTE
            return redirect('login')                                # ← AJOUTE
        return redirect('dashboard_transporteur')
    if request.user.is_superuser:
        return redirect('dashboard_admin_stats')
    return redirect('/admin/')
def catalogue_produits(request):
    maintenant = timezone.now().date()

    # --- Produits disponibles (offre) ---
    produits = ProduitAgricole.objects.filter(
        quantite_disponible__gt=0,
        date_peremption_prevue__gt=maintenant
    )

    query = request.GET.get('q')
    if query:
        produits = produits.filter(nom__icontains=query)
    zone_choisie = request.GET.get('zone')
    if zone_choisie:
        produits = produits.filter(zone_production=zone_choisie)
    prix_max = request.GET.get('prix_max')
    if prix_max:
        try:
            produits = produits.filter(prix_unitaire__lte=float(prix_max))
        except ValueError:
            pass

    # --- Filtre catégorie (pour tout le monde) ---
    categorie = request.GET.get('categorie')
    if categorie:
        produits = produits.filter(categorie=categorie)

    tri = request.GET.get('tri')
    if tri == 'prix':
        produits = produits.order_by('prix_unitaire')
    elif tri == 'date':
        produits = produits.order_by('-date_publication')
    elif tri == 'score':
        produits = produits.order_by('-producteur__score_confiance')
    else:
        produits = produits.order_by('-date_publication')

    # --- Demandes de marché (visibles uniquement par les producteurs) ---
    if hasattr(request.user, 'producteur_profil'):
        demandes_marche = DemandeMarche.objects.filter(statut='OUVERTE').order_by('-date_publication')
        if query:
            demandes_marche = demandes_marche.filter(produit__icontains=query)
        if zone_choisie:
            demandes_marche = demandes_marche.filter(marche__icontains=zone_choisie)
    else:
        demandes_marche = DemandeMarche.objects.none()

    context = {
        'produits': produits,
        'demandes_marche': demandes_marche,
        'aujourdhui': maintenant,
    }
    
    return render(request, 'gestion_agro/catalogue.html', context)
# --- DASHBOARD PRODUCTEUR FUSIONNÉ ---
@login_required
def dashboard_producteur(request):
    prod = get_object_or_404(Producteur, user=request.user)
    mes_produits = ProduitAgricole.objects.filter(producteur=prod).order_by('-date_publication')
    mes_reservations = Reservation.objects.filter(produit__producteur=prod).order_by('-date_reservation')

    # ========== NOUVEAU : transactions liées à ce producteur ==========
    transactions = Transaction.objects.filter(
        reservation__produit__producteur=prod
    ).order_by('-date_creation')

    # ========== NOUVEAU : notifications non lues ==========
    notifications = Notification.objects.filter(
        destinataire=request.user, lu=False
    ).order_by('-date_creation')
    nb_notifications = notifications.count()

    # --- RECALCUL AUTOMATIQUE DU SCORE DE CONFIANCE ---
    from django.db.models import F
    reservations_livrees = mes_reservations.filter(
        statut_caution='PAYE',
        livraison__statut='livre'
    )
    total_livrees = reservations_livrees.count()
    if total_livrees > 0:
        retards = Livraison.objects.filter(
            reservation__in=reservations_livrees,
            date_livraison_reelle__gt=F('reservation__date_disponibilite')
        ).count()
        litiges = Litige.objects.filter(
            livraison__reservation__in=reservations_livrees
        ).count()
        score = max(0, 100 - (retards * 2) - (litiges * 5))
        prod.score_confiance = int(score)
    else:
        prod.score_confiance = 100
    prod.save()

    # --- Alertes routières (toutes les alertes actives) ---
    alertes_route = AlerteSecuriteRoutiere.objects.filter(est_active=True).order_by('-date_publication')

    total_encaisse = mes_reservations.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    total_cautions_attente = mes_reservations.filter(statut_caution='NON_PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    reservations_validees = mes_reservations.filter(statut_caution='PAYE')
    reste_final = sum(res.reste_a_payer for res in reservations_validees)

    # --- Correction automatique du village pour la météo ---
    village = prod.village.strip() if prod.village else ""
    correspondances = {
        "cigaso": "Sikasso", "sikasoo": "Sikasso", "segou": "Segou",
        "mopti": "Mopti", "kayes": "Kayes", "kidal": "Kidal",
        "gao": "Gao", "tombouctou": "Tombouctou", "koutiala": "Koutiala",
        "bamako": "Bamako", "guinee": "Kankan", "fana": "Fana",
        "markala": "Markala", "san": "San",
    }
    village_lower = village.lower()
    if village_lower in correspondances:
        village = correspondances[village_lower]
    elif not village:
        village = "Bamako"
    villes_reconnues = [
        "Bamako", "Sikasso", "Segou", "Mopti", "Kayes", "Kidal", "Gao",
        "Tombouctou", "Koutiala", "Kankan", "Fana", "Markala", "San"
    ]
    if village not in villes_reconnues:
        village = "Bamako"

    from datetime import datetime, timedelta
    nouvelles_reservations = mes_reservations.filter(date_reservation__gte=datetime.now() - timedelta(hours=24))

    a_expedier_count = mes_reservations.filter(statut_caution='PAYE', statut_livraison='A_EXPEDIER').count()
    en_transit_count = mes_reservations.filter(statut_caution='PAYE', statut_livraison='EN_TRANSIT').count()
    res_logistique = {
        'a_expedier': a_expedier_count,
        'en_transit': en_transit_count,
    }

    # ========== STATISTIQUES LOGISTIQUES ==========
    stats_logistiques = None
    if mes_reservations.exists():
        livraisons_terminees = Livraison.objects.filter(
            reservation__in=mes_reservations,
            statut='livre',
            reservation__date_disponibilite__isnull=False
        )
        total_livraisons = livraisons_terminees.count()
        if total_livraisons > 0:
            from django.db.models import F, ExpressionWrapper, DurationField, Avg
            en_retard = livraisons_terminees.filter(
                date_livraison_reelle__gt=F('reservation__date_disponibilite')
            ).count()
            taux_ponctualite = round(((total_livraisons - en_retard) / total_livraisons) * 100, 1)

            delai_moyen = livraisons_terminees.annotate(
                diff=ExpressionWrapper(
                    F('date_livraison_reelle') - F('reservation__date_disponibilite'),
                    output_field=DurationField()
                )
            ).aggregate(moy=Avg('diff'))['moy']

            if delai_moyen:
                delai_jours = round(delai_moyen.total_seconds() / 86400, 1)
            else:
                delai_jours = 0

            stats_logistiques = {
                'taux_ponctualite': taux_ponctualite,
                'delai_moyen_jours': delai_jours,
                'nb_retard': en_retard,
            }

    # ========== ALERTES URGENTES ==========
    aujourdhui = timezone.now().date()
    recoltes_imminentes = ProduitAgricole.objects.filter(
        producteur=prod,
        statut_recolte='SUR_PIED',
        date_recolte_prevue__isnull=False,
        date_recolte_prevue__lte=aujourdhui + timedelta(days=3),
        date_recolte_prevue__gte=aujourdhui
    ).order_by('date_recolte_prevue')

    produits_urgents = ProduitAgricole.objects.filter(
        producteur=prod,
        quantite_disponible__gt=0,
        date_peremption_prevue__isnull=False,
        date_peremption_prevue__lte=aujourdhui + timedelta(days=3),
        date_peremption_prevue__gte=aujourdhui
    ).order_by('date_peremption_prevue')

    # --- Filtre par statut de disponibilité ---
    statut_filtre = request.GET.get('statut', 'actif')
    maintenant = timezone.now().date()

    if statut_filtre == 'actif':
        mes_produits = mes_produits.filter(
            quantite_disponible__gt=0,
            date_peremption_prevue__gte=maintenant
        )
    elif statut_filtre == 'epuise':
        mes_produits = mes_produits.filter(quantite_disponible=0)
    elif statut_filtre == 'perime':
        mes_produits = mes_produits.filter(date_peremption_prevue__lt=maintenant)
    elif statut_filtre == 'tous':
        pass
    else:
        mes_produits = mes_produits.filter(
            quantite_disponible__gt=0,
            date_peremption_prevue__gte=maintenant
        )

    # --- Conseils logistiques ---
    produits_sur_pied = mes_produits.filter(statut_recolte='SUR_PIED', date_recolte_prevue__isnull=False).order_by('date_recolte_prevue')
    produits_recoltes = mes_produits.filter(statut_recolte='RECOLTE')
    prochaine_recolte = produits_sur_pied.first()
    recolte_info = None
    if prochaine_recolte:
        jours_restants = (prochaine_recolte.date_recolte_prevue - aujourdhui).days
        recolte_info = {
            'nom': prochaine_recolte.nom,
            'date': prochaine_recolte.date_recolte_prevue.strftime('%d/%m/%Y'),
            'jours': jours_restants,
        }

    for p in mes_produits:
        if p.statut_recolte == 'SUR_PIED' and p.date_recolte_prevue:
            p.jours_avant_recolte = (p.date_recolte_prevue - aujourdhui).days
        else:
            p.jours_avant_recolte = None

    conseil_data = {
        'nb_sur_pied': produits_sur_pied.count(),
        'nb_recoltes': produits_recoltes.count(),
        'a_produits_perissables': mes_produits.filter(quantite_disponible__gt=0).exists(),
        'recolte_info': recolte_info,
    }

    demandes_marche = DemandeMarche.objects.all().order_by('-date_publication')[:5]

    historique_ventes = mes_reservations.filter(
        statut_caution='PAYE',
        livraison__statut='livre'
    ).order_by('-date_reservation')[:5]

    produits_vendus = mes_reservations.filter(statut_caution='PAYE').values('produit__nom').annotate(total=Sum('caution_20')).order_by('-total')
    donnees_graphique = list(produits_vendus)

    produits_carte = [p for p in mes_produits if hasattr(p, 'latitude') and p.latitude and p.longitude]
    livraisons_carte = []

    alertes_stock = []
    derniers_avis = []

    context = {
        'prod': prod,
        'produits': mes_produits,
        'reservations': mes_reservations,
        'total_encaisse': total_encaisse,
        'total_cautions_attente': total_cautions_attente,
        'reste_a_percevoir': reste_final,
        'total_en_vente': mes_produits.aggregate(Sum('quantite_disponible'))['quantite_disponible__sum'] or 0,
        'alertes_route': alertes_route,
        'alertes_stock': alertes_stock,
        'nouvelles_reservations': nouvelles_reservations,
        'res_logistique': res_logistique,
        'stats_logistiques': stats_logistiques,
        'produits_carte': produits_carte,
        'livraisons_carte': livraisons_carte,
        'village_producteur': village,
        'conseil_data': conseil_data,
        'statut_actuel': statut_filtre,
        'demandes_marche': demandes_marche,
        'historique_ventes': historique_ventes,
        'donnees_graphique': donnees_graphique,
        'derniers_avis': derniers_avis,
        'recoltes_imminentes': recoltes_imminentes,
        'produits_urgents': produits_urgents,
        'transactions': transactions,   # <-- ajouté précédemment
        'notifications': notifications,   # <-- nouveau
        'nb_notifications': nb_notifications,  # <-- nouveau
    }
    return render(request, 'gestion_agro/dashboard_producteur.html', context)
@login_required
def dashboard_commercant(request):
    commercant = get_object_or_404(Commercant, user=request.user)
    statut_filtre = request.GET.get('statut')
    mes_achats = Reservation.objects.filter(commercant=commercant).order_by('-date_reservation')
    if statut_filtre == 'en_cours':
        mes_achats = mes_achats.exclude(livraison__statut='LIVRE')
    elif statut_filtre == 'termine':
        mes_achats = mes_achats.filter(livraison__statut='LIVRE')

    # Transactions du commerçant
    mes_transactions = Transaction.objects.filter(
    reservation__commercant=commercant
).exclude(type_transaction='GAIN_TRANSPORT').order_by('-date_creation')

    # ========== NOUVEAU : notifications non lues ==========
    notifications = Notification.objects.filter(
        destinataire=request.user, lu=False
    ).order_by('-date_creation')
    nb_notifications = notifications.count()

    total_cautions_payees = mes_achats.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    total_reste_a_payer = sum(achat.reste_a_payer for achat in mes_achats if achat.statut_caution == 'PAYE')

    alertes_route = AlerteSecuriteRoutiere.objects.filter(est_active=True).order_by('-date_publication')[:3]
    demandes_marche = DemandeMarche.objects.all().order_by('-date_publication')[:5]

    mes_demandes = commercant.demandes.all().order_by('-date_publication')

    total_commandes = mes_achats.count()
    panier_moyen = (total_cautions_payees / total_commandes) if total_commandes > 0 else 0

    liste_produits = []
    for achat in mes_achats:
        nom = achat.produit.nom.strip()
        if nom.upper() not in [p.upper() for p in liste_produits]:
            liste_produits.append(nom)
    liste_produits.sort(key=str.lower)

    nb_retards = 0
    for achat in mes_achats:
        try:
            livraison = achat.livraison
            if livraison.statut == 'en_route' and livraison.date_chargement_reel:
                jours_ecoules = (timezone.now() - livraison.date_chargement_reel).days
                livraison.en_retard = jours_ecoules > 3
                if livraison.en_retard:
                    nb_retards += 1
            else:
                livraison.en_retard = False
        except Reservation.livraison.RelatedObjectDoesNotExist:
            pass

    from collections import defaultdict
    comparaison = defaultdict(list)
    for achat in mes_achats:
        prod_nom = achat.produit.nom.strip()
        vendeur_nom = achat.nom_du_producteur
        telephone = achat.produit.producteur.telephone if achat.produit.producteur else None
        score = achat.produit.producteur.score_confiance if achat.produit.producteur else 100
        prix = achat.produit.prix_unitaire
        if not any(v['nom'] == vendeur_nom for v in comparaison[prod_nom]):
            comparaison[prod_nom].append({
                'nom': vendeur_nom,
                'prix': prix,
                'score': score,
                'telephone': telephone,
            })

    from datetime import timedelta
    historique = defaultdict(list)
    maintenant = timezone.now()
    for i in range(6):
        debut_mois = maintenant.replace(day=1) - timedelta(days=30*i)
        fin_mois = (debut_mois.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        achats_periode = mes_achats.filter(
            date_reservation__gte=debut_mois,
            date_reservation__lte=fin_mois
        )
        for achat in achats_periode:
            prod_nom = achat.produit.nom.strip()
            if not any(h[0] == debut_mois.strftime('%m/%Y') for h in historique[prod_nom]):
                prix_moyen = achats_periode.filter(produit__nom__iexact=prod_nom).aggregate(Avg('produit__prix_unitaire'))['produit__prix_unitaire__avg']
                if prix_moyen:
                    historique[prod_nom].append((debut_mois.strftime('%m/%Y'), prix_moyen))

    context = {
        'commercant': commercant,
        'mes_achats': mes_achats,
        'total_cautions': total_cautions_payees,
        'total_reste_a_payer': total_reste_a_payer,
        'total_tonnage': mes_achats.aggregate(Sum('quantite_voulue'))['quantite_voulue__sum'] or 0,
        'nb_attente': mes_achats.filter(statut_caution='NON_PAYE').count(),
        'statut_actuel': statut_filtre,
        'alertes_route': alertes_route,
        'demandes_marche': demandes_marche,
        'mes_demandes': mes_demandes,
        'panier_moyen': panier_moyen,
        'liste_produits': liste_produits,
        'total_commandes': total_commandes,
        'nb_retards': nb_retards,
        'comparaison_producteurs': dict(comparaison) if comparaison else None,
        'historique_prix': dict(historique) if historique else None,
        'transactions': mes_transactions,
        'notifications': notifications,          # <-- ajouté
        'nb_notifications': nb_notifications,    # <-- ajouté
    }
    return render(request, 'gestion_agro/dashboard_commercant.html', context)
@login_required
def generer_recu(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if reservation.commercant.user != request.user:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    prix_total = reservation.produit.prix_unitaire * reservation.quantite_voulue
    context = {'res': reservation, 'date_emission': datetime.now(), 'prix_total': prix_total}
    return render(request, 'gestion_agro/recu_paiement.html', context)

@login_required
def confirmer_reception(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    
    # Vérification : seul le commerçant de la réservation peut confirmer
    if not hasattr(request.user, 'commercant_profil') or livraison.reservation.commercant.user != request.user:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    
    with transaction.atomic():
        livraison.statut = 'livre'
        livraison.date_livraison_reelle = timezone.now()
        livraison.save()
        res = livraison.reservation
        res.confirmation_producteur = True
        res.save()
        FluxProduit.objects.create(livraison=livraison, etape="Réception définitive confirmée par le commerçant", localisation=res.get_marche_destination_display())
    messages.success(request, "Réception confirmée avec succès !")
    return redirect('dashboard_commercant')

def calculer_distance(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371  # Rayon de la Terre en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    # Forcer a dans l'intervalle [0, 0.999999] pour éviter les erreurs d'arrondi
    a = max(0.0, min(0.999999, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c



@login_required
def dashboard_transporteur(request):
    transp = get_object_or_404(Transporteur, user=request.user)

    if request.method == "POST" and "toggle_dispo" in request.POST:
        transp.disponible = not transp.disponible
        transp.save()
        return redirect('dashboard_transporteur')

    missions_disponibles = Reservation.objects.filter(
        statut_caution='PAYE', livraison__isnull=True
    ).order_by('-date_reservation')

    alertes_route = AlerteSecuriteRoutiere.objects.filter(est_active=True)

    # Chargement des coordonnées depuis la base de données
    zones_dict = {z.nom: (z.latitude, z.longitude) for z in ZoneProduction.objects.all()}
    marches_dict = {m.nom: (m.latitude, m.longitude) for m in Marche.objects.all()}

    # Listes pour la carte
    zones_list = [{'nom': z.nom, 'latitude': z.latitude, 'longitude': z.longitude} for z in ZoneProduction.objects.all()]
    marches_list = [{'nom': m.nom, 'latitude': m.latitude, 'longitude': m.longitude} for m in Marche.objects.all()]

    PRIX_CARBURANT = 800

    missions_carte = []
    for m in missions_disponibles:
        m.distance_estimee = 150
        m.litres_carburant = 45
        m.temps_estime = 3.0
        m.temps_display = "3 h 00 min"
        m.gain_potentiel = 0
        m.rentable = False
        m.axe_dangereux = False

        zone = m.produit.zone_production.strip().upper()
        marche_raw = m.marche_destination.strip().upper()

        if zone in zones_dict and marche_raw in marches_dict:
            coord_depart = zones_dict[zone]
            coord_arrivee = marches_dict[marche_raw]
            distance_km = calculer_distance(coord_depart, coord_arrivee)
            m.distance_estimee = round(distance_km, 1)
            m.litres_carburant = round(distance_km * 0.35, 1)
            m.temps_estime = round(distance_km / 60, 1)
            m.gain_potentiel = int(distance_km * 60 * (m.quantite_voulue / 1000))
            m.rentable = True

            heures = int(m.temps_estime)
            minutes = int((m.temps_estime - heures) * 60)
            if heures == 0:
                m.temps_display = f"{minutes} min"
            else:
                m.temps_display = f"{heures} h {minutes:02d} min"

            axe = f"{zone} - {m.get_marche_destination_display()}"
            m.axe_dangereux = any(mot in axe for mot in alertes_route.values_list('axe_routier', flat=True))

            m.latitude_depart = coord_depart[0]
            m.longitude_depart = coord_depart[1]
            m.latitude_arrivee = coord_arrivee[0]
            m.longitude_arrivee = coord_arrivee[1]
            missions_carte.append(m)

        m.nom_producteur = m.produit.producteur.nom_complet if m.produit.producteur else ""
        m.nom_commercant = m.commercant.nom if m.commercant else ""
        m.date_disponibilite = m.date_disponibilite
        cout_carburant = int(m.litres_carburant * PRIX_CARBURANT)
        m.cout_carburant = cout_carburant
        m.gain_net = m.gain_potentiel - cout_carburant

        if transp.capacite_kg > 0:
            m.taux_remplissage = int((m.quantite_voulue / transp.capacite_kg) * 100)
        else:
            m.taux_remplissage = 0

        if m.gain_net > 0 and m.distance_estimee > 0:
            ratio = m.gain_net / m.distance_estimee
            m.score_rentabilite = min(10, max(1, int(ratio / 5)))
        else:
            m.score_rentabilite = 1

    # --- Groupage de missions ---
    from collections import defaultdict

    missions_groupees = defaultdict(list)
    for mission in missions_disponibles:
        cle_groupe = (
            mission.date_disponibilite,
            mission.produit.zone_production,
            mission.marche_destination
        )
        missions_groupees[cle_groupe].append(mission)

    groupes_a_afficher = {
        cle: missions for cle, missions in missions_groupees.items() if len(missions) >= 2
    }

    lots_resumes = []
    for cle, missions in groupes_a_afficher.items():
        date_dispo, zone, marche = cle
        gain_total = sum(m.gain_potentiel for m in missions)
        volume_total = sum(m.quantite_voulue for m in missions)
        noms_produits = ", ".join(sorted(set(m.produit.nom for m in missions)))
        ids_missions = [m.id for m in missions]
        taux_remplissage_lot = int((volume_total / transp.capacite_kg) * 100) if transp.capacite_kg > 0 else 0

        cout_carburant_total = sum(m.cout_carburant for m in missions)
        gain_net_lot = gain_total - cout_carburant_total
        distance_moyenne = missions[0].distance_estimee if missions else 300
        if gain_net_lot > 0 and distance_moyenne > 0:
            ratio_lot = gain_net_lot / distance_moyenne
            score_lot = min(10, max(1, int(ratio_lot / 5)))
        else:
            score_lot = 1

        lots_resumes.append({
            'date_disponibilite': date_dispo,
            'zone': zone,
            'marche': marche,
            'gain_total': gain_total,
            'volume_total': volume_total,
            'taux_remplissage': taux_remplissage_lot,
            'score_rentabilite': score_lot,
            'noms_produits': noms_produits,
            'missions': missions,
            'ids_missions': ids_missions,
        })

    # --- Suggestions de retour ---
    suggestions_retour = []
    zone_retour = 'SIKASSO'
    missions_retour = Reservation.objects.filter(
        statut_caution='PAYE',
        livraison__isnull=True,
        marche_destination=zone_retour
    ).exclude(
        produit__zone_production=zone_retour
    ).order_by('-date_reservation')

    for m in missions_retour:
        suggestions_retour.append({
            'id': m.id,
            'produit': m.produit.nom,
            'quantite': m.quantite_voulue,
            'depart': m.produit.zone_production,
            'arrivee': m.get_marche_destination_display(),
            'date': m.date_disponibilite,
        })

    livraisons_actives = Livraison.objects.filter(transporteur=transp).exclude(statut='livre').order_by('-id')
    historique = Livraison.objects.filter(transporteur=transp, statut='livre').order_by('-id')

    total_livraisons = historique.count()
    if total_livraisons > 0:
        retards = historique.filter(date_livraison_reelle__gt=F('reservation__date_disponibilite')).count()
        litiges = Litige.objects.filter(livraison__in=historique).count()
        score = max(0, 100 - (retards * 2) - (litiges * 5))
        transp.score_fiabilite = int(score)
    else:
        transp.score_fiabilite = 100
    transp.save()

    total_gains = sum(l.frais_transport for l in historique) if historique else 0
    transactions = Transaction.objects.filter(
       reservation__livraison__transporteur=transp,
       type_transaction='GAIN_TRANSPORT'
   ).order_by('-date_creation')


    notifications = Notification.objects.filter(
        destinataire=request.user, lu=False
    ).order_by('-date_creation')
    nb_notifications = notifications.count()

    context = {
        'transp': transp,
        'missions': missions_disponibles,
        'lots_resumes': lots_resumes,
        'suggestions_retour': suggestions_retour,
        'livraisons_actives': livraisons_actives,
        'historique': historique,
        'total_livraisons': total_livraisons,
        'alertes_route': alertes_route,
        'missions_carte': missions_carte,
        'total_gains': total_gains,
        'transactions': transactions,
        'notifications': notifications,
        'nb_notifications': nb_notifications,
        'zones_list': zones_list,
        'marches_list': marches_list,
    }
    return render(request, 'gestion_agro/dashboard_transporteur.html', context)
@login_required
def accepter_lot(request):
    if request.method == 'POST':
        ids_missions = request.POST.getlist('missions_ids')
        transporteur = get_object_or_404(Transporteur, user=request.user)
        if not transporteur.est_verifie:
            messages.error(request, "Votre compte doit être vérifié.")
            return redirect('verifier_identite')
        for mid in ids_missions:
            reservation = get_object_or_404(Reservation, id=mid)
            if not Livraison.objects.filter(reservation=reservation).exists():
                Livraison.objects.create(
                    reservation=reservation,
                    transporteur=transporteur,
                    statut='proposition',
                    frais_transport=0  # sera défini plus tard si nécessaire
                )
        messages.success(request, f"Lot de {len(ids_missions)} missions accepté.")
    return redirect('dashboard_transporteur')
@login_required
def accepter_mission(request, reservation_id):
    if request.method == "POST":
        reservation_obj = get_object_or_404(Reservation, id=reservation_id)
        transp = get_object_or_404(Transporteur, user=request.user)
        if not transp.est_verifie:
            messages.error(request, "Votre compte doit être vérifié pour accepter une mission.")
            return redirect('verifier_identite')
        
        tarif = request.POST.get('tarif_propose')
        
        try:
            with transaction.atomic():
                if not Livraison.objects.filter(reservation=reservation_obj).exists():
                    nouvelle_livraison = Livraison.objects.create(
                        reservation=reservation_obj,
                        transporteur=transp,
                        statut='proposition',
                        date_depart=timezone.now(),
                        tarif_propose=Decimal(tarif) if tarif else Decimal('0'),
                        frais_transport=Decimal(tarif) if tarif else Decimal('0')
                    )
                    FluxProduit.objects.create(
                        livraison=nouvelle_livraison,
                        etape="Transporteur intéressé - tarif proposé : {} FCFA".format(tarif),
                        localisation=reservation_obj.produit.zone_production
                    )
                    messages.success(request, "Votre proposition de tarif a été envoyée au commerçant.")
        except Exception as e:
            messages.error(request, f"Erreur : {e}")

    return redirect('dashboard_transporteur')
@login_required
def charger_marchandise(request, livraison_id):
    if request.method == "POST":
        livraison = get_object_or_404(Livraison, id=livraison_id, transporteur__user=request.user)
        with transaction.atomic():
            livraison.statut = 'en_route'
            livraison.date_chargement_reel = timezone.now()
            livraison.save()
            FluxProduit.objects.create(livraison=livraison, etape="Marchandise chargée au champ - Camion en route vers Bamako", localisation=livraison.reservation.produit.zone_production)
            messages.success(request, "Chargement validé. Bon voyage, soyez prudent sur la route !")
    return redirect('dashboard_transporteur')

@login_required
def terminer_livraison(request, livraison_id):
    if request.method == "POST":
        livraison = get_object_or_404(Livraison, id=livraison_id, transporteur__user=request.user)
        with transaction.atomic():
            livraison.statut = 'livre'
            livraison.date_livraison_reelle = timezone.now()
            livraison.save()
            res = livraison.reservation
            res.save()
            FluxProduit.objects.create(
                livraison=livraison,
                etape="Livraison effectuée - Colis déposé au marché",
                localisation=res.get_marche_destination_display()
            )
            # Création de la transaction pour le transporteur
            Transaction.objects.create(
                reservation=res,
                type_transaction='GAIN_TRANSPORT',
                montant=livraison.frais_transport,
                statut='EFFECTUE',
                commentaire=f"Gain pour la livraison #{livraison.id} par {request.user.username}"
            )
            messages.success(request, "Livraison clôturée avec succès.")
    return redirect('dashboard_transporteur')
@login_required
def marquer_notifications_lues(request):
    if request.method == 'POST':
        Notification.objects.filter(destinataire=request.user, lu=False).update(lu=True)
    return redirect(request.META.get('HTTP_REFERER', 'direction_vue'))
@login_required
def telecharger_bon_livraison(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    user = request.user
    autorise = False
    # Transporteur concerné
    if hasattr(user, 'transporteur_profil') and livraison.transporteur.user == user:
        autorise = True
    # Commerçant concerné
    if hasattr(user, 'commercant_profil') and livraison.reservation.commercant.user == user:
        autorise = True
    # Admin
    if user.is_superuser:
        autorise = True
    if not autorise:
        return HttpResponseForbidden("Accès refusé.")

    context = {'livraison': livraison}
    pdf = render_to_pdf('gestion_agro/bon_livraison.html', context)
    if pdf.status_code == 500:
        return HttpResponse("Erreur PDF", status=500)
    filename = f"bon_livraison_SANIAGRO_{livraison.id}.pdf"
    pdf['Content-Disposition'] = f'attachment; filename="{filename}"'
    return pdf
@login_required
def ajouter_produit(request):
    prod_obj = get_object_or_404(Producteur, user=request.user)
    if not prod_obj.est_verifie:
        messages.error(request, "Votre compte doit être vérifié pour publier un produit.")
        return redirect('verifier_identite')
    if request.method == "POST":
        per_date = request.POST.get('date_peremption_prevue')
        statut = request.POST.get('statut_recolte', 'SUR_PIED')
        
        # Gestion intelligente de la date de récolte selon le statut
        if statut == 'RECOLTE':
            rec_date = None  # Pas de date de récolte prévue pour un produit déjà récolté
        else:
            rec_date_str = request.POST.get('date_recolte_prevue')
            if rec_date_str:
                rec_date = datetime.strptime(rec_date_str, '%Y-%m-%d').date()
            else:
                rec_date = None
        
        nouveau_produit = ProduitAgricole(
            producteur=prod_obj,
            nom=request.POST.get('nom'),
            quantite_initiale=request.POST.get('quantite_initiale'),
            quantite_disponible=request.POST.get('quantite_initiale'),
            unite=request.POST.get('unite', 'KG'),
            prix_unitaire=request.POST.get('prix_unitaire'),
            zone_production=request.POST.get('zone_production'),
            zone_origine=request.POST.get('zone_origine'),
            statut_recolte=statut,
            date_recolte_prevue=rec_date,
            date_peremption_prevue=datetime.strptime(per_date, '%Y-%m-%d').date() if per_date else None,
            image=request.FILES.get('image'),
            video_demonstration=request.FILES.get('video_demonstration')
        )
        nouveau_produit.save()
        messages.success(request, "Produit publié avec succès !")
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/ajouter_produit.html')
@login_required
def modifier_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur__user=request.user)
    if request.method == "POST":
        produit.nom = request.POST.get('nom', produit.nom)
        produit.prix_unitaire = request.POST.get('prix_unitaire', produit.prix_unitaire)
        # ✅ Correction : on ne modifie zone_production que si une nouvelle valeur est envoyée
        nouvelle_zone = request.POST.get('zone_production')
        if nouvelle_zone:
            produit.zone_production = nouvelle_zone
        # ------------------------------------------------------------
        produit.statut_recolte = request.POST.get('statut_recolte', produit.statut_recolte)
        produit.date_recolte_prevue = request.POST.get('date_recolte_prevue') or None
        produit.date_peremption_prevue = request.POST.get('date_peremption_prevue') or None
        if request.FILES.get('image'):
            produit.image = request.FILES.get('image')
        if request.FILES.get('video_demonstration'):
            produit.video_demonstration = request.FILES.get('video_demonstration')
        produit.save()
        messages.success(request, "Produit mis à jour.")
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/modifier_produit.html', {'produit': produit})
@login_required
def supprimer_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur__user=request.user)
    if request.method == "POST":
        produit.delete()
        messages.success(request, "Produit supprimé du catalogue.")
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/confirmer_suppression.html', {'produit': produit})

@login_required
def modifier_photo_profil(request):
    if request.method == 'POST' and request.FILES.get('photo_profil'):
        prof = get_object_or_404(Producteur, user=request.user)
        prof.photo_profil = request.FILES['photo_profil']
        prof.save()
    return redirect('dashboard_producteur')

@login_required
def reserver_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id)
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Vous devez être inscrit comme commerçant pour réserver.")
        return redirect('direction_vue')
    if not request.user.commercant_profil.est_verifie:
        messages.error(request, "Votre compte doit être vérifié pour réserver un produit.")
        return redirect('verifier_identite')
    if request.method == "POST":
        quantite = int(request.POST.get('quantite_voulue', 0))
        if 0 < quantite <= produit.quantite_disponible:
            reservation = Reservation.objects.create(
                produit=produit,
                commercant=request.user.commercant_profil,
                quantite_voulue=quantite,
                marche_destination=request.POST.get('marche_destination'),
                mode_paiement=request.POST.get('mode_paiement', 'CASH'),
                date_disponibilite=produit.date_recolte_prevue
            )
            messages.success(request, "Réservation enregistrée. Veuillez maintenant payer la caution.")
            return redirect('valider_paiement_caution', reservation_id=reservation.id)
        else:
            messages.error(request, "Quantité invalide.")
    return render(request, 'gestion_agro/reserver.html', {'produit': produit})
@login_required
def valider_paiement_caution(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, commercant__user=request.user)
    if request.method == "POST":
        # Enregistrer la preuve de paiement
        preuve = request.FILES.get('preuve_paiement')
        if preuve:
            reservation.preuve_paiement = preuve
        reservation.statut_caution = 'ATTENTE_VALIDATION'   # nouveau statut (à créer)
        reservation.ref_transaction = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        reservation.save()
        messages.success(request, "Votre preuve de paiement a été envoyée. La caution est en attente de validation.")
        return redirect('dashboard_commercant')
    # GET : afficher la page de paiement
    return render(request, 'gestion_agro/confirmer_paiement.html', {'res': reservation})
@login_required    

def valider_la_caution(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, produit__producteur__user=request.user)
    reservation.statut_caution = 'PAYE'
    reservation.save()
    return redirect('dashboard_producteur')
@login_required
def choisir_transporteur(request, reservation_id):
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent choisir un transporteur.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, commercant=request.user.commercant_profil)

    if reservation.statut_caution not in ['BLOQUEE', 'PAYE']:
        messages.error(request, "La caution doit être validée avant de choisir un transporteur.")
        return redirect('dashboard_commercant')

    if hasattr(reservation, 'livraison'):
        messages.warning(request, "Un transporteur est déjà attribué à cette réservation.")
        return redirect('dashboard_commercant')

    transporteurs = Transporteur.objects.filter(disponible=True)

    return render(request, 'gestion_agro/choisir_transporteur.html', {
        'reservation': reservation,
        'transporteurs': transporteurs,
    })


@login_required
def attribuer_transporteur(request, reservation_id):
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Seuls les commerçants peuvent effectuer cette action.")
        return redirect('direction_vue')

    reservation = get_object_or_404(Reservation, id=reservation_id, commercant=request.user.commercant_profil)

    if reservation.statut_caution not in ['BLOQUEE', 'PAYE'] or hasattr(reservation, 'livraison'):
        messages.error(request, "Action impossible.")
        return redirect('dashboard_commercant')

    if request.method == "POST":
        transporteur_id = request.POST.get('transporteur_id')
        transporteur = get_object_or_404(Transporteur, id=transporteur_id, disponible=True)

        with transaction.atomic():
            Livraison.objects.create(
                reservation=reservation,
                transporteur=transporteur,
                statut='proposition',
                date_depart=timezone.now(),
                frais_transport=transporteur.tarif_base
            )
        messages.success(request, f"Le transporteur {transporteur.nom} a été attribué à votre commande.")
        return redirect('dashboard_commercant')
    else:
        return redirect('choisir_transporteur', reservation_id=reservation.id)

@login_required
def declarer_litige(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    user = request.user
    # Vérifier que l'utilisateur est impliqué dans la livraison
    est_commercant = hasattr(user, 'commercant_profil') and livraison.reservation.commercant.user == user
    est_producteur = hasattr(user, 'producteur_profil') and livraison.reservation.produit.producteur.user == user
    est_transporteur = hasattr(user, 'transporteur_profil') and livraison.transporteur.user == user
    if not (est_commercant or est_producteur or est_transporteur or user.is_superuser):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if request.method == "POST":
        motif_text = request.POST.get('motif')
        if motif_text:
            Litige.objects.create(livraison=livraison, declarant=request.user, motif=motif_text)
            messages.success(request, "Litige transmis à l'administrateur.")
            return redirect('direction_vue')
    return render(request, 'gestion_agro/declarer_litige.html', {'livraison': livraison})

@login_required
def dashboard_admin_stats(request):
    if not request.user.is_superuser:
        return redirect('direction_vue')

    # Cautions en attente
    cautions_attente = Reservation.objects.filter(statut_caution='ATTENTE_VALIDATION').order_by('-date_reservation')

    # Identités à vérifier
    producteurs_a_verifier = Producteur.objects.filter(est_verifie=False, piece_identite__isnull=False)
    commercants_a_verifier = Commercant.objects.filter(est_verifie=False, piece_identite__isnull=False)
    transporteurs_a_verifier = Transporteur.objects.filter(est_verifie=False, piece_identite__isnull=False)

    # Tous les utilisateurs pour la gestion blocage/déblocage
    tous_producteurs = Producteur.objects.all()
    tous_commercants = Commercant.objects.all()
    tous_transporteurs = Transporteur.objects.all()
    tous_litiges = Litige.objects.all().order_by('-date_creation')

    # Transactions en attente de traitement
    transactions_en_attente = Transaction.objects.filter(statut='EN_ATTENTE').order_by('-date_creation')
    nb_transactions_attente = transactions_en_attente.count()

    # ========== STATISTIQUES AVANCÉES (corrigées) ==========
    from django.db.models import Sum, Count, Q
    from datetime import date

    # Chiffre d'affaires total par produit (prix_total = caution + reste)
    ca_par_produit = Reservation.objects.filter(statut_caution='PAYE').values('produit__nom').annotate(
        total=Sum('prix_total')
    ).order_by('-total')

    # Chiffre d'affaires total par marché
    ca_par_marche = Reservation.objects.filter(statut_caution='PAYE').values('marche_destination').annotate(
        total=Sum('prix_total')
    ).order_by('-total')

    # Livraisons réussies ce mois-ci
    debut_mois = date.today().replace(day=1)
    livraisons_mois = Livraison.objects.filter(statut='livre', date_livraison_reelle__gte=debut_mois).count()

    # Top 3 transporteurs les plus fiables
    top_transporteurs = Transporteur.objects.all().order_by('-score_fiabilite')[:3]

    # Top 3 producteurs les plus actifs (nombre de ventes)
    top_producteurs = Producteur.objects.annotate(
        nb_ventes=Count('produits__reservation', filter=Q(produits__reservation__statut_caution='PAYE'))
    ).order_by('-nb_ventes')[:3]

    context = {
        'nb_litiges': Litige.objects.filter(resolu=False).count(),
        'argent_securise': Reservation.objects.filter(statut_caution='BLOQUEE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0,
        'flux_actif': Livraison.objects.filter(statut__in=['en_route', 'en_attente']).count(),
        'cautions_attente': cautions_attente,
        'nb_cautions': cautions_attente.count(),
        'producteurs_a_verifier': producteurs_a_verifier,
        'commercants_a_verifier': commercants_a_verifier,
        'transporteurs_a_verifier': transporteurs_a_verifier,
        'nb_identites': producteurs_a_verifier.count() + commercants_a_verifier.count() + transporteurs_a_verifier.count(),
        'tous_producteurs': tous_producteurs,
        'tous_commercants': tous_commercants,
        'tous_transporteurs': tous_transporteurs,
        'tous_litiges': tous_litiges,
        'transactions_en_attente': transactions_en_attente,
        'nb_transactions_attente': nb_transactions_attente,
        # Variables statistiques
        'ca_par_produit': ca_par_produit,
        'ca_par_marche': ca_par_marche,
        'livraisons_mois': livraisons_mois,
        'top_transporteurs': top_transporteurs,
        'top_producteurs': top_producteurs,
    }
    return render(request, 'gestion_agro/dashboard_admin.html', context)
def accueil(request):
    return render(request, 'index.html')

@login_required
def suivre_livraison(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    user = request.user
    # Vérifier que l'utilisateur est impliqué
    est_commercant = hasattr(user, 'commercant_profil') and livraison.reservation.commercant.user == user
    est_producteur = hasattr(user, 'producteur_profil') and livraison.reservation.produit.producteur.user == user
    est_transporteur = hasattr(user, 'transporteur_profil') and livraison.transporteur.user == user
    if not (est_commercant or est_producteur or est_transporteur or user.is_superuser):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    etapes = FluxProduit.objects.filter(livraison=livraison).order_by('-date_heure')
    return render(request, 'gestion_agro/suivre_livraison.html', {'livraison': livraison, 'etapes': etapes})

def inscription_choix(request):
    return render(request, 'registration/choix_role.html')

def inscription_final(request, role):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            photo = request.FILES.get('photo_profil')
            tel = request.POST.get('telephone')
            if role == 'producteur':
                Producteur.objects.create(user=user, nom_complet=request.POST.get('nom'), village=request.POST.get('village'), telephone=tel, photo_profil=photo)
            elif role == 'commercant':
                Commercant.objects.create(user=user, nom=request.POST.get('nom_famille'), prenom=request.POST.get('prenom'), telephone=tel, ville_marche=request.POST.get('ville_marche'))
            elif role == 'transporteur':
                Transporteur.objects.create(user=user, nom=request.POST.get('nom_compagnie'), telephone=tel, vehicule=request.POST.get('type_vehicule'), plaque_immatriculation=request.POST.get('numero_plaque'), tarif_base=request.POST.get('tarif_base', 0), photo_profil=photo)
            messages.success(request, f"Compte {role} créé avec succès !")
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, f'registration/inscription_{role}.html', {'form': form, 'role': role})

def clic_vendre(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'producteur_profil'): 
            return redirect('dashboard_producteur')
        return redirect('direction_vue')
    return redirect('inscription_final', role='producteur')

def clic_marche(request):
    return redirect('catalogue_produits')

def clic_transport(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'transporteur_profil'): 
            return redirect('dashboard_transporteur')
        return redirect('direction_vue')
    return redirect('inscription_final', role='transporteur')
@login_required
def marquer_recolte(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id)
    if produit.producteur.user != request.user:
        return HttpResponseForbidden("Action non autorisée.")
    if request.method == 'POST' and produit.statut_recolte == 'SUR_PIED':
        produit.statut_recolte = 'RECOLTE'
        produit.save()
        messages.success(request, "Statut du produit mis à jour : Récolté.")
    return redirect('dashboard_producteur')


@login_required
def changer_statut_livraison(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if reservation.produit.producteur.user != request.user:
        return HttpResponseForbidden("Action non autorisée.")
    if request.method == 'POST':
        nouveau_statut = request.POST.get('nouveau_statut')
        if nouveau_statut in ['EN_TRANSIT', 'LIVRE']:
            reservation.statut_livraison = nouveau_statut
            reservation.save()
            messages.success(request, f"Statut de livraison mis à jour : {nouveau_statut}.")
    return redirect('dashboard_producteur')
@login_required
def publier_demande_marche(request):
    if request.method == 'POST':
        commercant = get_object_or_404(Commercant, user=request.user)
        if not commercant.est_verifie:
            messages.error(request, "Votre compte doit être vérifié pour publier une demande.")
            return redirect('verifier_identite')
        DemandeMarche.objects.create(
            commercant=commercant,
            produit=request.POST.get('produit'),
            quantite=request.POST.get('quantite'),
            marche=request.POST.get('marche'),
            date_besoin=request.POST.get('date_besoin'),
        )
        messages.success(request, "Votre demande a été publiée avec succès !")
    return redirect('dashboard_commercant')
@login_required
def accepter_proposition(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id, reservation__commercant__user=request.user)
    livraison.statut = 'accepte'
    livraison.save()
    messages.success(request, "Proposition acceptée. Le transporteur peut maintenant charger la marchandise.")
    return redirect('dashboard_commercant')

@login_required
def refuser_proposition(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id, reservation__commercant__user=request.user)
    livraison.delete()
    messages.warning(request, "Proposition refusée. La mission est de nouveau disponible.")
    return redirect('dashboard_commercant')
@login_required
def bloquer_utilisateur(request, type_profil, profil_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    if type_profil == 'producteur':
        profil = get_object_or_404(Producteur, id=profil_id)
    elif type_profil == 'commercant':
        profil = get_object_or_404(Commercant, id=profil_id)
    elif type_profil == 'transporteur':
        profil = get_object_or_404(Transporteur, id=profil_id)
    else:
        return redirect('dashboard_admin_stats')
    
    profil.est_actif = False
    profil.save()
    messages.success(request, f"{profil} bloqué avec succès.")
    return redirect('dashboard_admin_stats')

@login_required
def debloquer_utilisateur(request, type_profil, profil_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    if type_profil == 'producteur':
        profil = get_object_or_404(Producteur, id=profil_id)
    elif type_profil == 'commercant':
        profil = get_object_or_404(Commercant, id=profil_id)
    elif type_profil == 'transporteur':
        profil = get_object_or_404(Transporteur, id=profil_id)
    else:
        return redirect('dashboard_admin_stats')
    
    profil.est_actif = True
    profil.save()
    messages.success(request, f"{profil} débloqué avec succès.")
    return redirect('dashboard_admin_stats')
@login_required
def dashboard_transactions_admin(request):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    transactions_en_attente = Transaction.objects.filter(statut='EN_ATTENTE').order_by('-date_creation')
    context = {'transactions': transactions_en_attente}
    return render(request, 'gestion_agro/dashboard_transactions.html', context)

@login_required
def telecharger_recu_transaction(request, transaction_id):
    transaction_obj = get_object_or_404(Transaction, id=transaction_id)

    # Vérification des droits d'accès
    user = request.user
    autorise = False
    if hasattr(user, 'producteur_profil'):
        if transaction_obj.reservation.produit.producteur.user == user:
            autorise = True
    if hasattr(user, 'commercant_profil'):
        if transaction_obj.reservation.commercant.user == user:
            autorise = True
    if hasattr(user, 'transporteur_profil'):
        livraison = getattr(transaction_obj.reservation, 'livraison', None)
        if livraison and livraison.transporteur.user == user:
            autorise = True
    if user.is_superuser:
        autorise = True

    if not autorise:
        return HttpResponseForbidden("Accès refusé.")

    # Génération du PDF
    context = {'transaction': transaction_obj}
    pdf = render_to_pdf('gestion_agro/recu_transaction.html', context)

    if pdf.status_code == 500:
        return HttpResponse("Erreur PDF", status=500)

    filename = f"recu_SANIAGRO_{transaction_obj.id}.pdf"
    pdf['Content-Disposition'] = f'attachment; filename="{filename}"'
    return pdf

@login_required
def marquer_transaction_effectue(request, transaction_id):
    if not request.user.is_superuser:
        return redirect('direction_vue')
    
    transaction = get_object_or_404(Transaction, id=transaction_id)
    transaction.marquer_effectue()
    messages.success(request, f"Transaction #{transaction.id} marquée comme effectuée.")
    return redirect('dashboard_transactions_admin')



