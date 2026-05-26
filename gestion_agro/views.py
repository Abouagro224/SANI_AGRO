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
from django.http import HttpResponseForbidden
from django.contrib.auth.forms import UserCreationForm

# Importation de tes modèles
from .models import ProduitAgricole, Producteur, Reservation, Commercant, Livraison, Transporteur, FluxProduit, Litige

# --- 1. AIGUILLAGE DETECTING ROLES ---
@login_required
def direction_vue(request):
    if Producteur.objects.filter(user=request.user).exists():
        return redirect('dashboard_producteur')
    elif Commercant.objects.filter(user=request.user).exists():
        return redirect('catalogue_produits')
    elif Transporteur.objects.filter(user=request.user).exists():
        return redirect('dashboard_transporteur')
    return redirect('/admin/')


# --- 2. CATALOGUE (ACCÈS PUBLIC AVEC SUPPORTS VIDÉOS) ---
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
    prod = get_object_or_404(Producteur, user=request.user)
    mes_produits = ProduitAgricole.objects.filter(producteur=prod).order_by('-date_publication')
    mes_reservations = Reservation.objects.filter(produit__producteur=prod).order_by('-date_reservation')
    
    total_encaisse = mes_reservations.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    total_cautions_attente = mes_reservations.filter(statut_caution='NON_PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    
    reservations_validees = mes_reservations.filter(statut_caution='PAYE')
    reste_final = sum(res.reste_a_payer for res in reservations_validees)

    context = {
        'prod': prod,
        'produits': mes_produits,
        'reservations': mes_reservations,
        'total_encaisse': total_encaisse,
        'total_cautions_attente': total_cautions_attente,
        'reste_a_percevoir': reste_final,
        'total_en_vente': mes_produits.aggregate(Sum('quantite_disponible'))['quantite_disponible__sum'] or 0,
    }
    return render(request, 'gestion_agro/dashboard_producteur.html', context)


# --- 4. DASHBOARD COMMERÇANT ---
@login_required
def dashboard_commercant(request):
    commercant = get_object_or_404(Commercant, user=request.user)
    statut_filtre = request.GET.get('statut')
    mes_achats = Reservation.objects.filter(commercant=commercant).order_by('-date_reservation')
    
    if statut_filtre == 'en_cours':
        mes_achats = mes_achats.exclude(livraison__statut='LIVRE')
    elif statut_filtre == 'termine':
        mes_achats = mes_achats.filter(livraison__statut='LIVRE')

    total_cautions_payees = mes_achats.filter(statut_caution='PAYE').aggregate(Sum('caution_20'))['caution_20__sum'] or 0
    total_reste_a_payer = sum(achat.reste_a_payer for achat in mes_achats if achat.statut_caution == 'PAYE')
    
    context = {
        'commercant': commercant,
        'mes_achats': mes_achats,
        'total_cautions': total_cautions_payees,
        'total_reste_a_payer': total_reste_a_payer, 
        'total_tonnage': mes_achats.aggregate(Sum('quantite_voulue'))['quantite_voulue__sum'] or 0,
        'nb_attente': mes_achats.filter(statut_caution='NON_PAYE').count(),
        'statut_actuel': statut_filtre,
    }
    return render(request, 'gestion_agro/dashboard_commercant.html', context)


@login_required
def generer_recu(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if reservation.commercant.user != request.user:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    prix_total = reservation.produit.prix_unitaire * reservation.quantite_voulue
    context = {
        'res': reservation,
        'date_emission': datetime.now(),
        'prix_total': prix_total,
    }
    return render(request, 'gestion_agro/recu_paiement.html', context)


@login_required
def confirmer_reception(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    with transaction.atomic():
        livraison.statut = 'livre'
        livraison.date_livraison_reelle = timezone.now() # Date obligatoire ajoutée
        livraison.save()
        
        res = livraison.reservation
        res.confirmation_producteur = True
        res.save()
        
        FluxProduit.objects.create(
            livraison=livraison,
            etape="Réception définitive confirmée par le commerçant",
            localisation=res.get_marche_destination_display()
        )
    messages.success(request, "Réception confirmée avec succès !")
    return redirect('dashboard_commercant')


# --- 5. DASHBOARD TRANSPORTEUR & TIMING LOGISTIQUE ---
@login_required
def dashboard_transporteur(request):
    transp = get_object_or_404(Transporteur, user=request.user)
    missions_disponibles = Reservation.objects.filter(statut_caution='PAYE', livraison__isnull=True).order_by('-date_reservation')

    for m in missions_disponibles:
        m.distance_estimee = 150 
        m.gain_potentiel = m.distance_estimee * 500 

    livraisons_actives = Livraison.objects.filter(transporteur=transp).exclude(statut='livre').order_by('-id')
    historique = Livraison.objects.filter(transporteur=transp, statut='livre').order_by('-id')

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
                        etape="Mission acceptée - En attente de chargement au champ",
                        localisation=reservation_obj.produit.zone_production
                    )
                    messages.success(request, "Mission acceptée ! Rendez-vous au champ.")
        except Exception as e:
            messages.error(request, f"Erreur : {e}")
    return redirect('dashboard_transporteur')


@login_required
def charger_marchandise(request, livraison_id):
    """Le transporteur est arrivé au champ et charge effectivement le camion"""
    if request.method == "POST":
        livraison = get_object_or_404(Livraison, id=livraison_id, transporteur__user=request.user)
        with transaction.atomic():
            livraison.statut = 'en_route'
            livraison.date_chargement_reel = timezone.now() # Date obligatoire logistique
            livraison.save()
            
            FluxProduit.objects.create(
                livraison=livraison,
                etape="Marchandise chargée au champ - Camion en route vers Bamako",
                localisation=livraison.reservation.produit.zone_production
            )
            messages.success(request, "Chargement validé. Bon voyage, soyez prudent sur la route !")
    return redirect('dashboard_transporteur')


@login_required
def terminer_livraison(request, livraison_id):
    if request.method == "POST":
        livraison = get_object_or_404(Livraison, id=livraison_id, transporteur__user=request.user)
        with transaction.atomic():
            livraison.statut = 'livre'
            livraison.date_livraison_reelle = timezone.now() # Date obligatoire logistique
            livraison.save()
            
            res = livraison.reservation
            res.save()
            
            FluxProduit.objects.create(
                livraison=livraison,
                etape="Livraison effectuée - Colis déposé au marché",
                localisation=res.get_marche_destination_display()
            )
            messages.success(request, "Livraison clôturée avec succès.")
    return redirect('dashboard_transporteur')


# --- 6. GESTION PRODUITS AVEC ENREGISTREMENT VIDÉO (PRODUCTEUR) --
@login_required
def ajouter_produit(request):
    prod_obj = get_object_or_404(Producteur, user=request.user)
    if request.method == "POST":
        # Récupération de la date de récolte
        rec_date = request.POST.get('date_recolte_prevue')
        # Récupération de la date de péremption saisie par le producteur
        per_date = request.POST.get('date_peremption_prevue')

        nouveau_produit = ProduitAgricole(
            producteur=prod_obj, 
            nom=request.POST.get('nom'),
            quantite_initiale=request.POST.get('quantite_initiale'),
            quantite_disponible=request.POST.get('quantite_initiale'),
            unite=request.POST.get('unite', 'KG'),
            prix_unitaire=request.POST.get('prix_unitaire'),
            zone_production=request.POST.get('zone_production'),
            zone_origine=request.POST.get('zone_origine'),
            statut_recolte=request.POST.get('statut_recolte', 'SUR_PIED'),
            # Conversion sécurisée
            date_recolte_prevue=datetime.strptime(rec_date, '%Y-%m-%d').date() if rec_date else None,
            date_peremption_prevue=datetime.strptime(per_date, '%Y-%m-%d').date() if per_date else None,
            image=request.FILES.get('image'),
            video_demonstration=request.FILES.get('video_demonstration')
        )
        
        # En appelant .save(), le modèle vérifie si date_peremption_prevue est vide.
        # Si le producteur a rempli le champ, le modèle le garde. Sinon, il le calcule.
        nouveau_produit.save()
        
        messages.success(request, "Produit publié avec succès !")
        return redirect('dashboard_producteur')
    return render(request, 'gestion_agro/ajouter_produit.html')
@login_required
def modifier_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id, producteur__user=request.user)
    if request.method == "POST":
        produit.nom = request.POST.get('nom')
        produit.prix_unitaire = request.POST.get('prix_unitaire')
        produit.zone_production = request.POST.get('zone_production')
        produit.statut_recolte = request.POST.get('statut_recolte')
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


# --- 7. RÉSERVATIONS ET PAIEMENTS ---
@login_required(login_url='login')  # <--- On force la redirection vers ton URL 'login'
def reserver_produit(request, produit_id):
    produit = get_object_or_404(ProduitAgricole, id=produit_id)
    
    # On vérifie si l'utilisateur est bien un commerçant
    if not hasattr(request.user, 'commercant_profil'):
        messages.error(request, "Vous devez être inscrit comme commerçant pour réserver.")
        return redirect('direction_vue')

    if request.method == "POST":
        quantite = int(request.POST.get('quantite_voulue', 0))
        if 0 < quantite <= produit.quantite_disponible:
            Reservation.objects.create(
                produit=produit, 
                commercant=request.user.commercant_profil,
                quantite_voulue=quantite,
                marche_destination=request.POST.get('marche_destination'),
                mode_paiement=request.POST.get('mode_paiement', 'CASH'),
                date_disponibilite=produit.date_recolte_prevue
            )
            messages.success(request, "Demande de réservation enregistrée !")
            return redirect('dashboard_commercant')
        else:
            messages.error(request, "Quantité invalide ou supérieure au stock disponible.")
            
    return render(request, 'gestion_agro/reserver.html', {'produit': produit})

@login_required
def valider_paiement_caution(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, commercant__user=request.user)
    if request.method == "POST":
        reservation.statut_caution = 'PAYE'
        reservation.ref_transaction = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        reservation.save()
        messages.success(request, "Paiement de la caution de 20% validé avec succès.")
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
            messages.success(request, "Litige transmis à l'administrateur.")
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


def accueil(request):
    return render(request, 'index.html')


@login_required
def suivre_livraison(request, livraison_id):
    livraison = get_object_or_404(Livraison, id=livraison_id)
    etapes = FluxProduit.objects.filter(livraison=livraison).order_by('-date_heure')
    return render(request, 'gestion_agro/suivre_livraison.html', {'livraison': livraison, 'etapes': etapes})


# --- 9. INSCRIPTIONS COMPLÈTES AVEC FILTRAGE DES PROFILS ---
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


# --- CORRECTIONS DES RELATED_NAMES DES PROFILS USER ---
def clic_vendre(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'producteur_profil'): 
            return redirect('dashboard_producteur')
        return redirect('direction_vue')
    return redirect('inscription_choix')


def clic_marche(request):
    return redirect('catalogue_produits')


def clic_transport(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'transporteur_profil'): 
            return redirect('dashboard_transporteur')
        return redirect('direction_vue')
    return redirect('inscription_choix')