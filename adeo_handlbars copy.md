<HTML>
<style>
    @charset "UTF-8";

    body {
        width: 21cm;
        height: 29.7cm;
        margin: 0.5cm 1.5cm;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
    }

    .header {
        display: flex;
        align-items: center;
        color: #9b9b9b;
        font-family: 'Leroy Merlin Sans', Helvetica, 'Arial';
    }

    .headerinfo {
        padding-left: .5cm;
    }

    .headertitle {
        font-size: 12pt;
        text-transform: uppercase;
        margin: 0;
    }

    .headertext {
        font-size: 7pt;
        margin: 0;
        padding: .1cm 0;
    }

    .order {
        color: #202020;
        margin: 0;
        padding: .1cm 0;
    }

    .logo {
        width: auto;
        height: 55px;
    }

    main h2 {
        padding: 0;
        margin: .25cm 0 .05cm 0;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        font-size: 12pt;
        text-transform: uppercase;
        font-weight: normal;
    }

    main fieldset {
        border: none;
        font-size: 10pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        padding: 0;
    }

    .input {
        background: #fff;
        font-size: 9pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        border: 0;
        min-width: 70%;
    }

    .row {
        display: flex;
        justify-content: space-between;
        align-items: start;
    }

    .fieldsetheader {
        margin-top: .2cm;
        display: flex;
        align-items: baseline;
    }

    .fieldsetheader h2 {
        margin: 0;
    }

    .fieldsetheader p {
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        margin: 0;
        padding-left: .3cm;
    }

    .cell {
        width: 50%;
    }

    textarea {
        border: 0;
        width: 100%;
        height: auto;
        background: #fff;
        font-size: 9pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        border: 0;
        overflow-y: hidden;
    }

    textarea.address {
        width: 100%;
        margin-right: 5px;
    }

    .cellborder {
        min-height: 2.5cm;
        border: 1px solid #9b9b9b;
        width: 100%;
        display: flex;
        align-items: flex-end;
        margin-right: .2cm;
    }

    .cellborder:last-child {
        margin: 0;
    }

    .cellborder p {
        padding-left: .3cm
    }

    footer p,
    small,
    .firm {
        font-size: 8pt;
    }

    .textdefault {
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        font-size: 9pt;
    }

    .list {
        list-style-type: none;
        padding-left: 0;
    }

    .listitem {
        padding-left: 0;
        border-bottom: 1px solid #9b9b9b;
    }

    .subitem {
        padding-left: 10px;
    }

    @media print {
        .block {
            page-break-inside: avoid;
        }
        .no-print,
        .no-print * {
            display: none !important;
        }
    }

    .print-page-end {
        page-break-after: right !important;
        clear: both !important;
    }
</style>
<div class="no-print">
    <button type="button" onClick="window.print()" ng-disabled="loading">
        PRINT
    </button>
</div>
<div ng-repeat="task in tasks track by task.id">
    <form>
        <header class="header">
            <img itemprop="image" class="logo"
                 src="data:image/png;base64,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"
                 alt="" width="" height=""/>
            <section class="headerinfo">
                <h1 class="headertitle">DOCUMENTO DE CONTROL DE TRANSPORTE DE MERCANC&Iacute;A POR CARRETERA</h1>
                <div class="row">
                    <p class="order">N&ordm; Pedido: {{task.title}}</p>
                </div>
            </section>
        </header>
        <main>
		<!--BRINGG NOTE: linked orders are managed as a 2 waypoint order with the Bringg Template Manager feature. Where the pickup will be the 1st waypoint i.e. "way_points[0]" and the dropoff the last waypoint i.e. "way_points[1]" -->
            <form>
                <!--ORIGEN-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos de Origen</h2>
                        <!--PICKUP INFORMATION</p>-->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
                            <!-- NAME -->
								<div ng-if="has_2wp(task)" class="cell">
								<!-- If order has 2 waypoints, display the 1st waypoint name -->
									<label for="nombreorigen"> Nombre : {{task.way_points[0].name}}</label>
								</div>
								<div ng-if="has_1wp(task)" class="cell">
								<!-- If order has 1 waypoint, display the team name -->
									<label for="nombreorigen"> Nombre : {{task.team.customer.name}}</label>
								</div>
							<!-- ADDRESS -->
								<div ng-if="has_2wp(task)" class="cell">
									<!-- If order has 2 waypoints, display the 1st waypoint address attributes: "address, city, zipcode, district" -->
										<label for="direccionfiscal"> Direcci&oacute;n: {{task.way_points[0].address}}, {{task.way_points[0].zipcode}}, {{task.way_points[0].city}}, {{task.way_points[0].district}}</label>
								</div>
								<div ng-if="has_1wp(task)" class="cell">
									<!-- If order has 1 waypoint, display the team  address attributes: "address, city, zipcode, district" -->
									<label for="direccionfiscal"> Direcci&oacute;n: {{task.team.customer.address}}, {{task.team.customer.zipcode}}, {{task.team.customer.city}}, {{task.team.customer.district}}</label>
								</div>
						</div>
                        <div class="row">
							<!-- NIF -->
								<div ng-if="has_2wp(task)" class="cell">
								<!-- If  order has 2 waypoints, display the OMES NIF information -->
									<label for="NIF"> NIF: B84406289</label> 
								</div>
								<!-- Effectively if task has only 1 waypoint, do not display any NIF information -->
                        </div>
                    </fieldset>
                </fieldset>
                <!--CARGADOR-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos del cargador</h2>
                        <!--OMES HEADQUARTERS INFORMATION-->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
                            <div class="cell"><label for="nombretienda"> Nombre: Bricolaje Bricoman. S.L.U</label> 
                            </div>
                            <div class="cell">
								<label for="direcciontienda"> Direcci&oacute;n: Calle margarita Salas 6, 28919, Leganes</label> 
							</div>
						</div>
                        <div class="row">
                            <div class="cell">
								<label for="niftienda"> NIF: B84406289</label> 
							</div>
						</div>
                    </fieldset>
                </fieldset>
                <!--OBSERVACIONES AL SERVICIO-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Observaciones al servicio</h2>
						<!-- PICKUP INSTRUCTIONS --> 
                    </section>
                    <fieldset class="fieldset">
                        <!-- display the 1st waypoint notes (ie pickup instructions) in a maximum of 100 characters -->
						<div class="row">
							<label maxlength="255">{{ getWayPointNote(task, task.way_points[0].id) }}</label>
						</div>
                    </fieldset>
                </fieldset>
                <!--TRANSPORTISTA-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos del transportista</h2>
						<!-- Carrier information based on driver's company data -->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
							<div ng-if="driverBelongsToCompany(task)" class="cell">
							<!-- Display company name, company phone and company tax id -->
								<label for="nombretransportista"> Nombre / Telephono / NIF:</label><br>{{task.user.company.name}}, {{task.user.company.phone}}, {{task.user.company.tax_id}}
							</div>
							<div ng-if="driverBelongsToCompany(task)" class="cell">
							<!-- Display company address -->
								<label for="direcciontransportista"> Direcci&oacute;n: {{task.user.company.address}}</label>
							</div>
						</div>
						<div ng-if="hasVehicle(task)" class="cell">
						<!-- Display vehicle license plate -->
							<label for="matriculas"> Matr&iacute;culas: {{task.vehicle.license_plate}}</label>
						</div>						
                    </fieldset>
                </fieldset>
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos del transportista efectivo</h2>
                    </section>
                    <fieldset class="fieldset">
						<!-- Empty block for driver/ company to write if needed -->
                        <textarea style="width: 60%; height: 25px; border-style: inset;border-width: 2px" id="datos_del_transportista_efectivo"></textarea>
                    </fieldset>
                </fieldset>
                <!--FECHA DE RECOGIDA-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Fecha de recogida</h2>
						<!-- Pickup date-->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
							<div class="cell">									
								<label for="fecharecogida"> Fecha de recogida: {{task.way_points[0].scheduled_at | date_only:task}}</label>
								<!-- Display the 1st waypoint (ie pickup) scheduled_at date -->
							</div>
							<div class="cell">
								<label for="horarecogida"> Hora de recogida: {{task.way_points[0].scheduled_at | time_only:task}}</label>
								<!-- Display the 1st waypoint (ie pickup) scheduled_at time -->
							</div>
                        </div>
                    </fieldset>
                </fieldset>
                <!--DROPOFF INSTRUCTIONS-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Observaciones del transportista</h2>
                    </section>
                    <fieldset class="fieldset">
						<!-- display the 2st waypoint (ie dropoff instructions)-->
						<div class="row">
							<label>{{ getWayPointNote(task, task.way_points[1].id) }}</label>
						</div>
                    </fieldset>
                </fieldset>
                <!--DATOS DEL DESTINO -->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos del destino</h2>
						<!-- DROP-OFF INFORMATION -->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
                            <!-- NAME -->
								<div ng-if="has_2wp(task)" class="cell">
									<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) name -->
									<label for="nombredestino"> Nombre cliente: {{task.way_points[1].name}}</label>
								</div>
								<div ng-if="has_1wp(task)" class="cell">
									<!-- If task has 1 waypoint, display the task team customer name -->
									<label for="nombredestino"> Nombre cliente: {{task.team.customer.name}}</label>
								</div>
							<!-- ADDRESS -->
								<div ng-if="has_2wp(task)" class="cell">
									<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) address -->
									<label for="direcciondestino"> Direcci&oacute;n: {{task.way_points[1].address}}</label>
							   </div>
								<div ng-if="has_1wp(task)" class="cell">
									<!-- If task has 1 waypoint, display the task team customer address -->
									<label for="direcciondestino"> Direcci&oacute;n: {{task.team.customer.address}}</label>
								</div>
                        </div>
						<div class="row">
							<!-- CITY -->
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) city -->
								<label for="localidaddestino"> Localidad: {{task.way_points[1].city}}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display the task team customer city -->
								<label for="localidaddestino"> Localidad: {{task.team.customer.city}}</label>
							</div>
							<!-- ZIPCODE -->
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) zipcode -->
								<label for="codigopostaldestino"> C&oacute;digo Postal: {{task.way_points[1].zipcode}}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display the task team customer zipcode -->
								<label for="codigopostaldestino"> C&oacute;digo Postal: {{task.team.customer.zipcode}}</label>
							</div>
                        </div>
                        <div class="row">
                            <!-- DISTRICT -->
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) district -->
								<label for="provinciadestino"> Provincia: {{task.way_points[1].district}}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display the task team customer district -->
								<label for="provinciadestino"> Provincia: {{task.team.customer.district}}</label>
							</div>
                            <!-- PHONE -->
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) phone -->
								<label for="telefonodestino"> Tel&eacute;fono: {{task.way_points[1].phone}}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display the task team customer phone -->
								<label for="telefonodestino"> Tel&eacute;fono: {{task.team.customer.phone}}</label>
							</div>
                        </div>
                    </fieldset>
                </fieldset>
				<!--DATOS DE LA ENTREGA / ORDER INFORMATION -->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Datos de la entrega</h2>
                    </section>
                    <fieldset class="fieldset">
						<div class="row">
								<div class="cell">
									<!-- Display the task external id ie Adeo transport order id -->
									<label for="albaran">N&ordm; orden de transporte: {{task.external_id}}</label>
								</div>
                        </div>
						<div class="row">
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) scheduled at day -->
								<label for="fechaentrega"> Fecha de entrega: {{task.way_points[1].scheduled_at | date_only:task }}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display the first waypoint (ie pickup) scheduled at day. The working assumption is the dropoff back at the team location will be done on the same day -->
								<label for="fechaentrega"> Fecha de entrega: {{task.way_points[0].scheduled_at | date_only:task }}</label>
							</div>
							<div ng-if="has_2wp(task)" class="cell">
								<!-- If task has 2 waypoints, display the last waypoint (ie drop-off) scheduled at time -->
								<label for="horaentrega"> Hora de entrega: {{task.way_points[1].scheduled_at | time_only:task }}</label>
							</div>
							<div ng-if="has_1wp(task)" class="cell">
								<!-- If task has 1 waypoint, display 8am-8pm -->
								<label for="horaentrega"> Hora de entrega: 08:00 - 20:00</label>
							</div>
                        </div>
						<div class="row">
                            <div class="cell">
								<!-- Display the inventories total weight -->
								<label for="peso"> Peso: {{ getTotalWeight(task) }} KG</label>
							</div>
                            <div class="cell">
								<!-- Display the nb of parent inventories -->
								<label for="bultos"> N&ordm; de bultos: {{task.way_point.task_inventories.length}}</label>
							</div>
                        </div>
                    </fieldset>
                </fieldset>
                <!--Observaciones a la entrega -->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Observaciones a la entrega</h2>
						<!-- Space for transport company to add their comments about the delivery -->
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
                            <textarea style="width: 60%; height: 20px; border-style: inset;border-width: 2px" id="observaciones_a_la_entrega"></textarea>
                        </div>
                    </fieldset>
                </fieldset>
                <!--INVENTARIO-->
                <fieldset class="block">
                    <section class="fieldsetheader">
                        <h2>Inventario</h2>
						<!-- TASK INVENTORY DATA -->
                    </section>
                    <fieldset class="fieldset">
                        <ul class="list">
                            <div ng-if="has_2wp(task)" ng-repeat="task_inventory in task.way_point.task_inventories track by task_inventory.id">
								<!-- Loop through parent inventories -->
									<li class="listitem">{{task_inventory.scan_string}} {{!task_inventory.weight && '' || task_inventory.weight && '- '+ task_inventory.weight.toLocaleString('es') +'kg'}}</li>
								<!-- Loop through sub inventories -->
									<li class="listitem subitem" ng-repeat="inventory in task_inventory.inventories track by inventory.id">{{inventory.original_quantity}} x {{inventory.name}} {{!inventory.weight && '' || inventory.weight && '- '+ inventory.weight.toLocaleString('es') +'kg'}}</li>
							</div>
							<div ng-if="has_1wp(task)" ng-repeat="task_inventory in task.way_point.task_inventories track by task_inventory.id">
								<!-- Loop through parent inventories -->
									<li class="listitem">{{task_inventory.original_quantity}} x {{task_inventory.inventory.name}} | {{task_inventory.scan_string}} | {{!task_inventory.weight && '' || task_inventory.weight.toLocaleString('es') +'kg'}}</li>
							</div>
						</ul>
                    </fieldset>
                </fieldset>
                <!--FORMA DE PAGO-->
                <fieldset>
                    <section class="fieldsetheader">
                        <h2>Datos de pago</h2>
                    </section>
                    <fieldset class="fieldset">
                        <div class="row">
                            <!-- Delivery cost --> 
							<div class="cell">
								<label for="formapago"> Importe: {{task.delivery_cost}} &euro;</label>
                            </div>
                        </div>
                        <div class="row">
                            <div class="cell"><input id="portepagado" checked="checked" type="checkbox" value="pagado"/>
								<label for="portepagado"> Portes pagados </label>
							</div>
							<div class="cell"><input id="portedebido" type="checkbox" value="debido"/>
								<label for="portedebido">Porte debido</label>
							</div>
                        </div>
                    </fieldset>
                </fieldset>
                <!--FORMA DE PAGO-->
                <fieldset class="block">
                    <fieldset class="fieldset">
                        <div class="row">
                            <div class="cellborder">
                                <p class="firm">Firma y sello del cargador</p>
                            </div>
                            <div class="cellborder">
                                <p class="firm">Firma y sello del transportista</p>
                            </div>
                            <div class="cellborder">
                                <p class="firm">Firma y sello del destinatario</p>
                            </div>
                        </div>
                    </fieldset>
                </fieldset>
                <!--RAEE-->
                <fieldset class="block">
                    <fieldset class="">
                        <div class="row">
                            <p class="textdefault">Marcar con una X la casilla SI o la casilla NO seg&uacute;n el
                                cliente haga entrega o no, respectivamente, de aparato/s usado/s al transportista que
                                presta sus servicios a Bricolaje Bricoman S.L.U. para su correcta gesti&oacute;n seg&uacute;n
                                Real Decreto 110/2015, de 20 de febrero, sobre Residuos de Aparatos El&eacute;ctricos y
                                Electr&oacute;nicos (RAEE).</p>
                        </div>
                        <div class="row">
                            <div class="cell">
								<label for="si1"> <input id="si1" type="checkbox" value="si1"/> S&iacute;</label>
                                <label for="no1"> <input id="no1" type="checkbox" value="no1"/> NO </label>
							</div>
                            <div class="cell">
								<label for="tipoRAEE1"> Tipo RAEE: </label> <input id="tipoRAEE1" class="input" type="text" value=""/>
                            </div>
                            <div class="cell"><label for="marcaRAEE1"> Marca: </label> <input id="marcaRAEE1" class="input" type="text" value=""/>
                            </div>
                        </div>
                        <div class="row">
                            <div class="cell">
								<label for="si1"><input id="si2" type="checkbox" value="si1"/> S&iacute;</label>
                                <label for="no1"><input id="no2" type="checkbox" value="no1"/> NO </label>
							</div>
                            <div class="cell">
								<label for="tipoRAEE2"> Tipo RAEE: </label> <input id="tipoRAEE2" class="input" type="text" value=""/>
                            </div>
                            <div class="cell">
								<label for="marcaRAEE2"> Marca: </label> <input id="marcaRAEE2" class="input" type="text" value=""/>
                            </div>
                        </div>
                        <div class="row">
                            <div class="cell">
								<label for="si1"> <input id="si3" type="checkbox" value="si1"/> S&iacute;</label>
                                <label for="no1"> <input id="no3" type="checkbox" value="no1"/> NO </label>
							</div>
                            <div class="cell">
								<label for="tipoRAEE3"> Tipo RAEE: </label> <input id="tipoRAEE3" class="input" type="text" value=""/>
                            </div>
                            <div class="cell">
								<label for="marcaRAEE3"> Marca: </label> <input id="marcaRAEE3" class="input" type="text" value=""/>
                            </div>
                        </div>
                        <div class="row">
                            <p class="textdefault">
                                Para el caso de que el cliente haya marcado la opci&oacute;n de NO realizar la entrega
                                del aparato usado y desechado, de caracter&iacute;sticas o funcionalidades similares a
                                las del aparato nuevo, se le informa de la posibilidad de entregar el viejo aparato en
                                cualquiera de los puntos de venta de Bricolaje Bricoman S.L.U., en un plazo m&aacute;ximo
                                de 30 d&iacute;as a contar desde la entrega del citado nuevo aparato, siempre y cuando
                                se presente la correspondiente factura de compra del nuevo aparato el&eacute;ctrico y/o
                                electr&oacute;nico
                            </p>
                            <div class="cellborder">
                                <p class="firm">Firma del cliente</p>
                            </div>
                        </div>
                    </fieldset>
                </fieldset>
            </form>
        </main>
    </form>
    <footer>
        <div class="row">
            <small>1&ordf; Hoja ejemplar para cliente</small>
            <small>2&ordf; Hoja ejemplar para transportista</small>
            <small>3&ordf; Hoja ejemplar para Alcam&eacute;n</small>
        </div>
    </footer>
    <div class="print-page-end">&nbsp;</div>
</div>
</HTML>
QA_OMES_Bringg_Template_v1.html
Displaying QA_OMES_Bringg_Template_v1.html.