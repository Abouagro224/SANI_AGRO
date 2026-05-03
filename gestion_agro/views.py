from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
import uuid 
from django.db import IntegrityError
from django.utils import timezone
from datetime import datetime
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseForbidden


# Importation de tes modèles
from .models import ProduitAgricole, Producteur, Reservation, Commercant, Livraison, Transporteur, FluxProduit, Litige

# --- 1. AIGUILLAGE ---
@login_required
def direction_vue(request):
    if Producteur.objects.filter(user=request.user).exists():
        return redirect('dashboard_producteur')
    elif Commercant.objects.filter(user=request.user).exists():
        return redirect('catalogue_produits')
    elif Transporteur.objects.filter(user=request.user).exists():
        return redirect('dashboard_transporteur')
    return redirect('/admin/')

# --- 2. CATALOGUE ---
def catalogue_produits(request):
    produits = ProduitAgricole.objects.filter(quantite_disponible__gt=0).order_by('-date_publication')
    query = request.GET.get('q')
    if query:
        produits = produits.filter(nom__icontains=query)
    
    zone_choisie = request.GET.get('zone')
    if zone_choisie:
        produits = produits.filter(zone_production=zone_choisie)

    return render(request, 'gestion_agro/catalogue.html', {'produits': produits})

# --- 3. DASHBOARD PRODUCTEUR ---
@login_required
def dashboard_producteur(request):
    # On récupère le profil du producteur connecté
    prod = get_object_or_404(Producteur, user=request.user)
    
    # On récupère ses produits et les réservations qui concernent SES produits
    mes_produits = ProduitAgricole.objects.filter(producteur=prod).order_by('-date_publication')
    mes_reservations = Reservation.objects.filter(produit__producteur=prod).order_by('-date_reservation')
    
    # CALCULS FINANCIERS PROFESSIONNELS
    # 1. Total des cautions (20%) déjà payées par les commerçants
    total_encaisse = mes_reservations.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    
    # 2. Total des cautions en attente (argent qui doit arriver)
    total_cautions_attente = mes_reservations.filter(statut_caution='NON_PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    
    # 3. LE RESTE À PERCEVOIR (Les 80% restants sur les ventes validées)
    # On utilise la propriété 'reste_a_payer' qu'on a ajoutée au modèle
    reservations_validees = mes_reservations.filter(statut_caution='PAYE')
    reste_final = sum(res.reste_a_payer for res in reservations_validees)

    context = {
        'prod': prod,
        'produits': mes_produits,
        'reservations': mes_reservations,
        'total_encaisse': total_encaisse,
        'total_cautions_attente': total_cautions_attente,
        'reste_a_percevoir': reste_final, # Somme des 80% restants
        'total_en_vente': mes_produits.aggregate(Sum('quantite_disponible'))['quantite_disponible__sum'] or 0,
    }
    return render(request, 'gestion_agro/dashboard_producteur.html', context)
# --- 4. DASHBOARD COMMERÇANT ---
@login_required
def dashboard_commercant(request):
    # On récupère le profil du commerçant connecté
    commercant = get_object_or_404(Commercant, user=request.user)
    
    # --- DÉBUT AJOUT FILTRAGE (SANS MODIFIER TON CODE) ---
    statut_filtre = request.GET.get('statut')
    # --- FIN AJOUT FILTRAGE ---

    # On récupère tous ses achats (réservations)
    mes_achats = Reservation.objects.filter(commercant=commercant).order_by('-date_reservation')
    
    # --- LOGIQUE DE FILTRAGE PROFESSIONNEL ---
    # --- LOGIQUE DE FILTRAGE CORRIGÉE ---
    if statut_filtre == 'en_cours':
        # On filtre les réservations qui ne sont pas encore marquées comme LIVRÉES dans la partie livraison
        mes_achats = mes_achats.exclude(livraison__statut='LIVRE')
    elif statut_filtre == 'termine':
        # On filtre pour voir uniquement celles qui sont déjà livrées
        mes_achats = mes_achats.filter(livraison__statut='LIVRE')
    # --- FIN LOGIQUE FILTRAGE ---
    # CALCULS FINANCIERS PROFESSIONNELS (Tes calculs restent intacts)
    total_cautions_payees = mes_achats.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    total_reste_a_payer = sum(achat.reste_a_payer for achat in mes_achats if achat.statut_caution == 'PAYE')
    
    context = {
        'commercant': commercant,
        'mes_achats': mes_achats,
        'total_cautions': total_cautions_payees,
        'total_reste_a_payer': total_reste_a_payer, 
        'total_tonnage': mes_achats.aggregate(Sum('quantite_voulue'))['quantite_voulue__sum'] or 0,
        'nb_attente': mes_achats.filter(statut_caution='NON_PAYE').count(),
        'statut_actuel': statut_filtre, # On ajoute ceci pour que le HTML sache quel bouton est allumé
    }
    return render(request, 'gestion_agro/dashboard_commercant.html', context)
@login_required
def generer_recu(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    
    if reservation.commercant.user != request.user:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    # CORRECTION : Utilise le bon nom de champ (prix_unitaire au lieu de prix)
    # D'après tes modèles précédents, c'est 'prix_unitaire'
    prix_total = reservation.produit.prix_unitaire * reservation.quantite_voulue

    context = {
        'res': reservation,
        'date_emission': datetime.now(),
        'prix_total': prix_total,
    }
    return render(request, 'gestion_agro/recu_paiement.html', context)

@login_required
def confirmer_reception(request, livraison_id):
    """ Action du Commerçant pour clore la livraison """
    livraison = get_object_or_404(Livraison, id=livraison_id)
    with transaction.atomic():
        livraison.statut = 'LIVRE'
        livraison.date_arrivee_estimee = timezone.now()
        livraison.save()
        
        res = livraison.reservation
        res.statut = 'TERMINE'
        res.confirmation_producteur = True
        res.save()
        
        FluxProduit.objects.create(
            livraison=livraison,
            etape="Réception confirmée au marché",
            localisation=res.get_marche_destination_display()
        )
    return redirect('dashboard_commercant')

# --- 5. DASHBOARD TRANSPORTEUR ---
@login_required
def dashboard_transporteur(request):
    transp = get_object_or_404(Transporteur, user=request.user)
    
    missions_disponibles = Reservation.objects.filter(
        statut_caution='PAYE', 
        livraison__isnull=True
    ).order_by('-date_reservation')

    for m in missions_disponibles:
        m.distance_estimee = 150 
        m.gain_potentiel = m.distance_estimee * 500 

    # Synchronisé avec le statut de la fonction accepter_mission
    livraisons_actives = Livraison.objects.filter(transporteur=transp, statut='en_attente').order_by('-id')
    historique = Livraison.objects.filter(transporteur=transp, statut='LIVRE').order_by('-id')

    context = {
        'transp': transp,
        'missions': missions_disponibles,
        'livraisons_actives': livraisons_actives,
        'historique': historique,
        'total_livraisons': historique.count(),
        'nb_dispo': missions_disponibles.count(),
    }
    return render(request, 'gestion_agro/dashboard_transporteur.html', context)

@login_required
def accepter_mission(request, reservation_id):
    if request.method == "POST":
        reservation_obj = get_object_or_404(Reservation, id=reservation_id)
        transp = get_object_or_404(Transporteur, user=request.user)
        
        try:
            with transaction.atomic():
                if not Livraison.objects.filter(reservation=reservation_obj).exists():
                    gain_mission = Decimal('150') * Decimal('500') 

                    nouvelle_livraison = Livraison.objects.create(
                        reservation=reservation_obj, 
                        transporteur=transp,
                        statut='en_attente',
                        date_depart=timezone.now(),
                        frais_transport=gain_mission
                    )

                    FluxProduit.objects.create(
                        livraison=nouvelle_livraison,
                        etape="Mission acceptée - En attente de chargement",
                        localisation=reservation_obj.produit.zone_production
                    )
                    messages.success(request, "Mission acceptée !")
        except Exception as e:
            messages.error(request, f"Erreur : {e}")
            
    return redirect('dashboard_transporteur')

@login_required
def terminer_livraison(request, livraison_id):
    if request.method == "POST":
        livraison = get_object_or_404(Livraison, id=livraison_id, transporteur__user=request.user)
        with transaction.atomic():
            livraison.statut = 'LIVRE'
            livraison.date_arrivee_estimee = timezone.now()
            livraison.save()
            
            res = livraison.reservation
            res.statut = 'TERMINE'
            res.save()

            FluxProduit.objects.create(
                livraison=livraison,
                etape="Livraison effectuée",
                localisation=res.get_marche_destination_display()
            )
    return redirect('dashboard_transporteur')

# --- 6. GESTION PRODUITS (PRODUCTEUR) ---
@login_required
def ajouter_produit(request):
    prod_obj = get_object_or_404(Producteur, user=request.user)
    if request.method == "POST":
        ProduitAgricole.objects.create(
            producteur=prod_obj, 
            nom=request.POST.get('nom'),
            quantite_initiale=request.POST.get('quantite_initiale'),
            quantite_disponible=request.POST.get('quantite_initiale'),
            unite=request.POST.get('unite', 'KG'),
            prix_unitaire=request.POST.get('prix_unitaire'),
            zone_origine=request.POST.get('zone_origine'),
            statut_recolte=request.POST.get('statut_recolte', 'SUR_PIED'),
            image=request.FILES.get('image')
        )
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/ajouter_produit.html')

@login_required
def modifier_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur__user=request.user)
    if request.method == "POST":
        produit.nom = request.POST.get('nom')
        produit.prix_unitaire = request.POST.get('prix_unitaire')
        if request.FILES.get('image'): produit.image = request.FILES.get('image')
        produit.save()
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/modifier_produit.html', {'produit': produit})

@login_required
def supprimer_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur__user=request.user)
    if request.method == "POST":
        produit.delete()
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/confirmer_suppression.html', {'produit': produit})

@login_required
def modifier_photo_profil(request):
    if request.method == 'POST' and request.FILES.get('photo_profil'):
        prof = get_object_or_404(Producteur, user=request.user)
        prof.photo_profil = request.FILES['photo_profil']
        prof.save()
    return redirect('dashboard_producteur')

# --- 7. RÉSERVATIONS ET PAIEMENTS ---
@login_required
def reserver_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id)
    commercant = get_object_or_404(Commercant, user=request.user)
    if request.method == "POST":
        quantite = int(request.POST.get('quantite_voulue', 0))
        if 0 < quantite <= produit.quantite_disponible:
            Reservation.objects.create(
                produit=produit, 
                commercant=commercant,
                quantite_voulue=quantite,
                marche_destination=request.POST.get('marche_destination'),
                mode_paiement=request.POST.get('mode_paiement', 'CASH')
            )
            return redirect('dashboard_commercant')
    return render(request, 'gestion_agro/reserver.html', {'produit': produit})

@login_required
def valider_paiement_caution(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, commercant__user=request.user)
    if request.method == "POST":
        reservation.statut_caution = 'PAYE'
        reservation.ref_transaction = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        reservation.save()
        messages.success(request, f"Paiement caution validé.")
        return redirect('dashboard_commercant')
    return render(request, 'gestion_agro/confirmer_paiement.html', {'res': reservation})

@login_required
def valider_la_caution(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, produit__producteur__user=request.user)
    reservation.statut_caution = 'PAYE'
    reservation.save()
    return redirect('dashboard_producteur')

# --- 8. LITIGES ET ADMIN ---
@login_required
def declarer_litige(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    if request.method == "POST":
        motif_text = request.POST.get('motif')
        if motif_text:
            Litige.objects.create(livraison=livraison, declarant=request.user, motif=motif_text)
            messages.success(request, "Litige transmis.")
            return redirect('direction_vue')
    return render(request, 'gestion_agro/declarer_litige.html', {'livraison': livraison})

@login_required
def dashboard_admin_stats(request):
    if not request.user.is_staff: return redirect('direction_vue')
    context = {
        'nb_litiges': Litige.objects.filter(resolu=False).count(),
        'argent_securise': Reservation.objects.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0,
        'flux_actif': Livraison.objects.filter(statut='en_attente').count(),
    }
    return render(request, 'gestion_agro/dashboard_admin.html', context)
@login_required
def suivre_livraison(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    # On utilise date_heure (le nom exact dans ta base de données)
    etapes = FluxProduit.objects.filter(livraison=livraison).order_by('-date_heure')
    
    return render(request, 'gestion_agro/suivre_livraison.html', {
        'livraison': livraison,
        'etapes': etapes
    })
